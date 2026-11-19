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
# 4. 互動按鈕、招募看板與滿員通知邏輯 (View)
# ==========================================
class RecruitView(discord.ui.View):
    def __init__(self, data):
        super().__init__(timeout=None)
        self.data = data
        self.notified_full = False

        if self.data["mode"] == "all_jobs":
            self.remove_item(self.join_tank)
            self.remove_item(self.join_healer)
            self.remove_item(self.join_dps)
            self.join_any.label = f"＋ 報名 / 取消 (0/{self.data['max_total']})"
        else:
            self.remove_item(self.join_any)

    def _current_count(self) -> int:
        if self.data["mode"] == "all_jobs":
            return len(self.data["members"])
        return (
            len(self.data["tanks"])
            + len(self.data["healers"])
            + len(self.data["dps"])
        )

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

        embed.set_footer(text=f"目前人數：{total}/{max_total} ｜ 點擊下方按鈕即可登記或取消")
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

    def _sync_role_buttons(self):
        self.join_tank.label = f"＋ 登記 Tank ({len(self.data['tanks'])}/2)"
        self.join_healer.label = f"＋ 登記 Healer ({len(self.data['healers'])}/2)"
        self.join_dps.label = f"＋ 登記 DPS ({len(self.data['dps'])}/4)"

    async def _toggle_role(
        self,
        interaction: discord.Interaction,
        role_key: str,
        limit: int,
        role_display: str,
    ):
        user = interaction.user
        target_list = self.data[role_key]

        if any(m.id == user.id for m in target_list):
            self.data[role_key] = [m for m in target_list if m.id != user.id]
            await interaction.response.send_message(
                f"已取消登記 {role_display}。", ephemeral=True
            )
        elif len(target_list) >= limit:
            await interaction.response.send_message(
                f"❌ {role_display} 已經額滿囉！", ephemeral=True
            )
            return
        else:
            for key in ("tanks", "healers", "dps"):
                self.data[key] = [m for m in self.data[key] if m.id != user.id]
            self.data[role_key].append(user)
            await interaction.response.send_message(
                f"✅ 成功登記為 {role_display}！", ephemeral=True
            )

        self._sync_role_buttons()
        await interaction.message.edit(embed=self.create_embed(), view=self)
        await self._check_and_notify_full(interaction)

    @discord.ui.button(
        label="＋ 登記 Tank (0/2)",
        style=discord.ButtonStyle.primary,
        custom_id="join_tank",
    )
    async def join_tank(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._toggle_role(interaction, "tanks", 2, "Tank")

    @discord.ui.button(
        label="＋ 登記 Healer (0/2)",
        style=discord.ButtonStyle.success,
        custom_id="join_healer",
    )
    async def join_healer(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._toggle_role(interaction, "healers", 2, "Healer")

    @discord.ui.button(
        label="＋ 登記 DPS (0/4)",
        style=discord.ButtonStyle.danger,
        custom_id="join_dps",
    )
    async def join_dps(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._toggle_role(interaction, "dps", 4, "DPS")

    @discord.ui.button(
        label="＋ 報名 / 取消",
        style=discord.ButtonStyle.primary,
        custom_id="join_any",
    )
    async def join_any(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        user = interaction.user
        members = self.data["members"]
        max_total = self.data["max_total"]

        if any(m.id == user.id for m in members):
            self.data["members"] = [m for m in members if m.id != user.id]
            await interaction.response.send_message("已取消報名。", ephemeral=True)
        elif len(members) >= max_total:
            await interaction.response.send_message(
                f"❌ 隊伍已經額滿（{max_total}/{max_total}）囉！", ephemeral=True
            )
            return
        else:
            members.append(user)
            await interaction.response.send_message("✅ 成功報名參加！", ephemeral=True)

        button.label = f"＋ 報名 / 取消 ({len(self.data['members'])}/{max_total})"
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
    await interaction.
