import os
import threading
import traceback
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
# 2. FF14 職能與職業清單設定
# ==========================================
ROLE_CONFIG = {
    "tanks": {
        "limit": 2,
        "display": "Tank",
        "emoji": "🛡️",
        "label_prefix": "＋ 選 Tank",
        "jobs": [
            ("PLD", "騎士 (PLD)"),
            ("WAR", "戰士 (WAR)"),
            ("DRK", "暗黑騎士 (DRK)"),
            ("GNB", "絕槍戰士 (GNB)"),
        ],
    },
    "healers": {
        "limit": 2,
        "display": "Healer",
        "emoji": "💚",
        "label_prefix": "＋ 選 Healer",
        "jobs": [
            ("WHM", "白魔法師 (WHM)"),
            ("SCH", "學者 (SCH)"),
            ("AST", "占星術士 (AST)"),
            ("SGE", "賢者 (SGE)"),
        ],
    },
    "dps": {
        "limit": 4,
        "display": "DPS",
        "emoji": "⚔️",
        "label_prefix": "＋ 選 DPS",
        "jobs": [
            ("MNK", "武僧 (MNK) - 近戰"),
            ("DRG", "龍騎士 (DRG) - 近戰"),
            ("NIN", "忍者 (NIN) - 近戰"),
            ("SAM", "武士 (SAM) - 近戰"),
            ("RPR", "钐鐮客 (RPR) - 近戰"),
            ("VPR", "蝰蛇劍士 (VPR) - 近戰"),
            ("BRD", "吟遊詩人 (BRD) - 遠敏"),
            ("MCH", "機工士 (MCH) - 遠敏"),
            ("DNC", "舞者 (DNC) - 遠敏"),
            ("BLM", "黑魔法師 (BLM) - 法系"),
            ("SMN", "召喚師 (SMN) - 法系"),
            ("RDM", "赤魔法師 (RDM) - 法系"),
            ("PCT", "繪靈法師 (PCT) - 法系"),
        ],
    },
}


# ==========================================
# 3. 初始化 Discord 機器人
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
# 4. 招募彈出視窗 (Modal)
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
            self.max_slots_input.default = "8"
            self.max_slots_input.label = "規定職能編制固定為 8 人 (2T / 2H / 4D)"

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
# 5. 職能專屬職業選擇下拉選單 View
# ==========================================
class JobSelectView(discord.ui.View):
    def __init__(
        self,
        parent_view: "RecruitView",
        role_key: str,
        board_message: discord.Message,
    ):
        super().__init__(timeout=60)
        self.parent_view = parent_view
        self.role_key = role_key
        self.board_message = board_message
        cfg = ROLE_CONFIG[role_key]

        options = [
            discord.SelectOption(label=job_label, value=job_label)
            for _, job_label in cfg["jobs"]
        ]
        options.append(
            discord.SelectOption(
                label="❌ 取消此職能 / 退出目前報名",
                value="__CANCEL__",
                description="若你已報名，點此可取消登記",
            )
        )

        select = discord.ui.Select(
            placeholder=f"選擇你的 {cfg['display']} 職業...",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        chosen = interaction.values[0]
        await self.parent_view.apply_job_selection(
            interaction=interaction,
            role_key=self.role_key,
            chosen_job=None if chosen == "__CANCEL__" else chosen,
            board_message=self.board_message,
        )


# ==========================================
# 6. 主招募看板 View
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
            self._sync_role_button_labels()

    def _sync_role_button_labels(self):
        for role_key, button in (
            ("tanks", self.join_tank),
            ("healers", self.join_healer),
            ("dps", self.join_dps),
        ):
            cfg = ROLE_CONFIG[role_key]
            count = len(self.data[role_key])
            button.label = f"{cfg['label_prefix']} ({count}/{cfg['limit']})"

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
            self.data[key] = [
                entry for entry in self.data[key] if entry["user"].id != user_id
            ]
            if len(self.data[key]) < before:
                removed = True
        return removed

    def _format_role_list(self, role_key: str) -> str:
        entries = self.data[role_key]
        if not entries:
            return "（尚無）"
        return "\n".join(
            [f"{entry['user'].mention} — **{entry['job']}**" for entry in entries]
        )

    def create_embed(self):
        total = self._current_count()
        max_total = self.data["max_total"]
        is_full = total >= max_total

        mode_text = (
            "規定職能 (2T / 2H / 4D・自選職業)"
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
            embed.add_field(
                name=f"🛡️ 坦克 Tank ({len(self.data['tanks'])}/2)",
                value=self._format_role_list("tanks"),
                inline=False,
            )
            embed.add_field(
                name=f"💚 治療 Healer ({len(self.data['healers'])}/2)",
                value=self._format_role_list("healers"),
                inline=False,
            )
            embed.add_field(
                name=f"⚔️ 輸出 DPS ({len(self.data['dps'])}/4)",
                value=self._format_role_list("dps"),
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
            text=f"目前人數：{total}/{max_total} ｜ 點擊職能按鈕後從選單挑選職業"
        )
        return embed

    async def _check_and_notify_full(self, interaction: discord.Interaction):
        total_members = self._current_count()
        max_total = self.data["max_total"]

        if total_members >= max_total and not self.notified_full and interaction.channel:
            self.notified_full = True
            if self.data["mode"] == "all_jobs":
                roster_users = self.data["members"]
            else:
                roster_users = [
                    entry["user"]
                    for key in ("tanks", "healers", "dps")
                    for entry in self.data[key]
                ]

            all_members = [self.data["leader"]] + roster_users
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

    async def _open_job_selector(
        self, interaction: discord.Interaction, role_key: str
    ):
        cfg = ROLE_CONFIG[role_key]
        target_list = self.data[role_key]
        already_in_this_role = any(
            entry["user"].id == interaction.user.id for entry in target_list
        )

        if not already_in_this_role and len(target_list) >= cfg["limit"]:
            await interaction.response.send_message(
                f"❌ {cfg['display']} 已經額滿（{cfg['limit']}/{cfg['limit']}）囉！",
                ephemeral=True,
            )
            return

        selector_view = JobSelectView(
            parent_view=self,
            role_key=role_key,
            board_message=interaction.message,
        )
        await interaction.response.send_message(
            f"請選擇你想加入的 **{cfg['display']}** 職業：",
            view=selector_view,
            ephemeral=True,
        )

    async def apply_job_selection(
        self,
        interaction: discord.Interaction,
        role_key: str,
        chosen_job: str | None,
        board_message: discord.Message,
    ):
        user = interaction.user
        cfg = ROLE_CONFIG[role_key]
        target_list = self.data[role_key]

        try:
            # 1. 取消報名
            if chosen_job is None:
                removed = self._remove_user_from_all_roles(user.id)
                self._sync_role_button_labels()
                msg = (
                    "已取消你的目前職能報名。"
                    if removed
                    else "你目前尚未在任何職能名單中。"
                )
                if not interaction.response.is_done():
                    await interaction.response.edit_message(content=msg, view=None)
                else:
                    await interaction.edit_original_response(content=msg, view=None)

                await board_message.edit(embed=self.create_embed(), view=self)
                return

            # 2. 檢查目標職能是否已額滿
            existing_in_target = next(
                (entry for entry in target_list if entry["user"].id == user.id), None
            )
            if existing_in_target is None and len(target_list) >= cfg["limit"]:
                err_msg = f"❌ {cfg['display']} 剛剛已經額滿囉！"
                if not interaction.response.is_done():
                    await interaction.response.edit_message(content=err_msg, view=None)
                else:
                    await interaction.edit_original_response(content=err_msg, view=None)
                return

            # 3. 更新名單並回應選單互動，再更新看板
            self._remove_user_from_all_roles(user.id)
            target_list.append({"user": user, "job": chosen_job})
            self._sync_role_button_labels()

            ok_msg = f"✅ 已登記為 **{cfg['display']} — {chosen_job}**！"
            if not interaction.response.is_done():
                await interaction.response.edit_message(content=ok_msg, view=None)
            else:
                await interaction.edit_original_response(content=ok_msg, view=None)

            await board_message.edit(embed=self.create_embed(), view=self)
            await self._check_and_notify_full(interaction)

        except Exception:
            print("apply_job_selection 發生例外：")
            traceback.print_exc()

    @discord.ui.button(
        label="＋ 選 Tank (0/2)",
        style=discord.ButtonStyle.primary,
        custom_id="join_tank",
    )
    async def join_tank(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._open_job_selector(interaction, "tanks")

    @discord.ui.button(
        label="＋ 選 Healer (0/2)",
        style=discord.ButtonStyle.success,
        custom_id="join_healer",
    )
    async def join_healer(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._open_job_selector(interaction, "healers")

    @discord.ui.button(
        label="＋ 選 DPS (0/4)",
        style=discord.ButtonStyle.danger,
        custom_id="join_dps",
    )
    async def join_dps(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._open_job_selector(interaction, "dps")

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

        if user in members:
            members.remove(user)
            await interaction.response.send_message("已取消報名。", ephemeral=True)
        elif len(members) >= max_total:
            await interaction.response.send_message(
                f"❌ 隊伍已經額滿（{max_total}/{max_total}）囉！", ephemeral=True
            )
            return
        else:
            members.append(user)
            await interaction.response.send_message("✅ 成功報名參加！", ephemeral=True)

        button.label = f"＋ 報名 / 取消 ({len(members)}/{max_total})"
        await interaction.message.edit(embed=self.create_embed(), view=self)
        await self._check_and_notify_full(interaction)


# ==========================================
# 7. 註冊斜線指令與啟動機器人
# ==========================================
@bot.tree.command(name="recruit", description="發布一個新的 FF14 隊伍招募")
@app_commands.describe(mode="選擇「規定職能 (2T/2H/4D)」或「所有職業 (不限職能)」")
@app_commands.choices(
    mode
