import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Literal
import discord
from discord import app_commands
from discord.ext import commands


# ==========================================
# 1. Render Web Service 健康檢查伺服器
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


# ==========================================
# 2. 初始化 Discord 機器人
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"成功同步 {len(synced)} 個指令。目前登入身分：{bot.user}")
    except Exception as e:
        print(f"指令同步失敗：{e}")


# ==========================================
# 3. 招募彈出視窗 (Modal)
# ==========================================
class RecruitModal(discord.ui.Modal):
    title_input = discord.ui.TextInput(
        label="招募標題 / 副本名稱",
        placeholder="例如：極神渡劫 / G15 挖寶車 / 刷坐騎",
        max_length=100,
    )
    max_slots_input = discord.ui.TextInput(
        label="隊伍總人數上限（預設 8 人，可填 2～24）",
        placeholder="8",
        default="8",
        max_length=2,
        required=True,
    )
    description = discord.ui.TextInput(
        label="詳細說明與要求",
        placeholder="例如：自備水藥食物、需看過攻略、集合地點...",
        style=discord.TextStyle.paragraph,
        max_length=400,
        required=False,
    )

    def __init__(self, mode: Literal["role_restricted", "all_jobs"]):
        mode_label = (
            "規定職能 (2T/2H/4D)"
            if mode == "role_restricted"
            else "所有職業 (不限職能)"
        )
        super().__init__(title=f"發布招募｜{mode_label}")
        self.mode = mode

        if mode == "role_restricted":
            self.remove_item(self.max_slots_input)

    async def on_submit(self, interaction: discord.Interaction):
        if self.mode == "role_restricted":
            max_total = 8
        else:
            raw_slots = (self.max_slots_input.value or "8").strip()
            if not raw_slots.isdigit() or not (2 <= int(raw_slots) <= 24):
                await interaction.response.send_message(
                    "❌ 人數上限請輸入 2 到 24 之間的數字！", ephemeral=True
                )
                return
            max_total = int(raw_slots)

        party_data = {
            "leader": interaction.user,
            "mode": self.mode,
            "max_total": max_total,
            "title": self.title_input.value,
            "desc": self.description.value or "無特別說明",
            "tanks": [],
            "healers": [],
            "dps": [],
            "members": [],
        }

        view = RecruitView(party_data)
        embed = view.create_embed()
        await interaction.response.send_message(embed=embed, view=view)


# ==========================================
# 4. 全下拉選單招募看板與滿員通知邏輯 (View)
# ==========================================
class RecruitView(discord.ui.View):
    def __init__(self, data):
        super().__init__(timeout=None)
        self.data = data
        self.notified_full = False

        self.select = discord.ui.Select(
            placeholder="請從下拉選單選擇要登記或取消的項目...",
            min_values=1,
            max_values=1,
        )
        self.select.callback = self.on_select_changed
        self._rebuild_select_options()
        self.add_item(self.select)

    def _current_count(self) -> int:
        if self.data["mode"] == "all_jobs":
            return len(self.data["members"])
        return (
            len(self.data["tanks"])
            + len(self.data["healers"])
            + len(self.data["dps"])
        )

    def _remove_user_from_all_roles(self, user_id: int) -> bool:
        removed = False
        for key in ("tanks", "healers", "dps"):
            before = len(self.data[key])
            self.data[key] = [m for m in self.data[key] if m.id != user_id]
            if len(self.data[key]) < before:
                removed = True
        return removed

    def _rebuild_select_options(self):
        if self.data["mode"] == "all_jobs":
            total = len(self.data["members"])
            max_total = self.data["max_total"]
            self.select.placeholder = f"所有職業報名 ({total}/{max_total}) — 點此選擇..."
            self.select.options = [
                discord.SelectOption(
                    label=f"＋ 報名參加隊伍 ({total}/{max_total})",
                    value="join_all",
                    description="加入目前的隊伍名單",
                ),
                discord.SelectOption(
                    label="－ 取消目前報名",
                    value="leave_all",
                    description="從已報名名單中退出",
                ),
            ]
        else:
            t_len = len(self.data["tanks"])
            h_len = len(self.data["healers"])
            d_len = len(self.data["dps"])
            self.select.placeholder = "選擇職能（2T / 2H / 4D）或取消報名..."
            self.select.options = [
                discord.SelectOption(
                    label=f"🛡️ 登記坦克 Tank ({t_len}/2)",
                    value="tanks",
                    description="加入坦克職能（上限 2 人）",
                ),
                discord.SelectOption(
                    label=f"💚 登記治療 Healer ({h_len}/2)",
                    value="healers",
                    description="加入治療職能（上限 2 人）",
                ),
                discord.SelectOption(
                    label=f"⚔️ 登記輸出 DPS ({d_len}/4)",
                    value="dps",
                    description="加入輸出職能（上限 4 人）",
                ),
                discord.SelectOption(
                    label="－ 取消目前職能報名",
                    value="cancel_role",
                    description="退出目前的職能登記並釋放名額",
                ),
            ]

    def create_embed(self):
        total = self._current_count()
        max_total = self.data["max_total"]
        is_full = total >= max_total

        mode_text = (
            "規定職能 (2T / 2H / 4D)"
            if self.data["mode"] == "role_restricted"
            else "所有職業（不限職能）"
        )

        embed = discord.Embed(
            title=f"⚔️ FF14 隊伍招募：{self.data['title']}",
            description=f"**職業模式：** {mode_text}\n\n{self.data['desc']}",
            color=discord.Color.green() if is_full else discord.Color.gold(),
        )
        embed.set_author(
            name=f"隊長：{self.data['leader'].display_name}",
            icon_url=self.data["leader"].display_avatar.url
            if self.data["leader"].display_avatar
            else None,
        )

        if self.data["mode"] == "role_restricted":
            tank_str = "\n".join([m.mention for m in self.data["tanks"]]) or "（尚無）"
            healer_str = "\n".join([m.mention for m in self.data["healers"]]) or "（尚無）"
            dps_str = "\n".join([m.mention for m in self.data["dps"]]) or "（尚無）"

            embed.add_field(
                name=f"🛡️ 坦克 Tank ({len(self.data['tanks'])}/2)",
                value=tank_str,
                inline=False,
            )
            embed.add_field(
                name=f"💚 治療 Healer ({len(self.data['healers'])}/2)",
                value=healer_str,
                inline=False,
            )
            embed.add_field(
                name=f"⚔️ 輸出 DPS ({len(self.data['dps'])}/4)",
                value=dps_str,
                inline=False,
            )
        else:
            members_str = "\n".join(
                [f"{idx + 1}. {m.mention}" for idx, m in enumerate(self.data["members"])]
            ) or "（尚無）"
            embed.add_field(
                name=f"👥 已報名成員 ({total}/{max_total})",
                value=members_str,
                inline=False,
            )

        embed.set_footer(
            text=f"目前人數：{total}/{max_total} ｜ 請使用下方下拉選單進行登記或取消"
        )
        return embed

    async def _check_and_notify_full(self, interaction: discord.Interaction):
        total_members = self._current_count()
        max_total = self.data["max_total"]

        if total_members >= max_total and not self.notified_full and interaction.channel:
            self.notified_full = True
            if self.data["mode"] == "all_jobs":
                roster = self.data["members"]
            else:
                roster = (
                    self.data["tanks"]
                    + self.data["healers"]
                    + self.data["dps"]
                )

            all_members = [self.data["leader"]] + roster
            unique_mentions = []
            seen_ids = set()
            for member in all_members:
                if member.id not in seen_ids:
                    seen_ids.add(member.id)
                    unique_mentions.append(member.mention)

            await interaction.channel.send(
                f"🎉 **隊伍已滿員（{total_members}/{max_total}）！** {' '.join(unique_mentions)}\n"
                f"招募主題：**{self.data['title']}** — 隊長與隊員可以準備集合出發囉！"
            )

    async def on_select_changed(self, interaction: discord.Interaction):
        choice = self.select.values[0]
        user = interaction.user

        if self.data["mode"] == "all_jobs":
            members = self.data["members"]
            max_total = self.data["max_total"]

            if choice == "join_all":
                if any(m.id == user.id for m in members):
                    await interaction.response.send_message(
                        "你已經在已報名名單中囉！", ephemeral=True
                    )
                    return
                if len(members) >= max_total:
                    await interaction.response.send_message(
                        f"❌ 隊伍已經額滿（{max_total}/{max_total}）囉！",
                        ephemeral=True,
                    )
                    return
                members.append(user)
                feedback = "✅ 成功報名參加！"
            else:
                before = len(members)
                self.data["members"] = [m for m in members if m.id != user.id]
                if len(self.data["members"]) == before:
                    await interaction.response.send_message(
                        "你目前尚未報名此隊伍。", ephemeral=True
                    )
                    return
                feedback = "已取消報名。"
        else:
            role_limits = {
                "tanks": (2, "Tank"),
                "healers": (2, "Healer"),
                "dps": (4, "DPS"),
            }

            if choice == "cancel_role":
                removed = self._remove_user_from_all_roles(user.id)
                if not removed:
                    await interaction.response.send_message(
                        "你目前尚未在任何職能名單中。", ephemeral=True
                    )
                    return
                feedback = "已取消你的目前職能報名。"
            else:
                limit, role_display = role_limits[choice]
                target_list = self.data[choice]
                already_in_target = any(m.id == user.id for m in target_list)

                if not already_in_target and len(target_list) >= limit:
                    await interaction.response.send_message(
                        f"❌ {role_display} 已經額滿（{limit}/{limit}）囉！",
                        ephemeral=True,
                    )
                    return

                self._remove_user_from_all_roles(user.id)
                if not already_in_target:
                    target_list.append(user)
                feedback = f"✅ 已登記為 {role_display}！"

        self._rebuild_select_options()
        await interaction.response.send_message(feedback, ephemeral=True)
        if interaction.message is not None:
            await interaction.message.edit(embed=self.create_embed(), view=self)
        await self._check_and_notify_full(interaction)


# ==========================================
# 5. 註冊斜線指令與啟動機器人
# ==========================================
@bot.tree.command(name="recruit", description="發布一個新的 FF14 隊伍招募")
@app_commands.describe(mode="選擇「規定職能 (2T/2H/4D)」或「所有職業 (不限職能)」")
@app_commands.choices(
    mode=[
        app_commands.Choice(name="規定職能 (2T / 2H / 4D)", value="role_restricted"),
        app_commands.Choice(name="所有職業 (不限職能)", value="all_jobs"),
    ]
)
async def recruit_command(
    interaction: discord.Interaction,
    mode: app_commands.Choice[str] = None,
):
    selected_mode = mode.value if mode else "role_restricted"
    await interaction.response.send_modal(RecruitModal(mode=selected_mode))


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("找不到 DISCORD_TOKEN 環境變數，請先在雲端或系統環境變數中設定。")

start_health_server()
bot.run(token)
