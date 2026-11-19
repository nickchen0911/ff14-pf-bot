import os
import discord
from discord.ext import commands

# 1. 初始化機器人
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


# 2. 招募彈出視窗 (Modal)
class RecruitModal(discord.ui.Modal, title="發布 FF14 隊伍招募 (Party Finder)"):
    title_input = discord.ui.TextInput(
        label="招募標題 / 副本名稱",
        placeholder="例如：極神渡劫 / G15 挖寶車 6缺2",
        max_length=100,
    )
    description = discord.ui.TextInput(
        label="詳細說明與要求",
        placeholder="例如：自備水藥食物，需看過攻略，通關後...",
        style=discord.TextStyle.paragraph,
        max_length=400,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        party_data = {
            "leader": interaction.user,
            "title": self.title_input.value,
            "desc": self.description.value or "無特別說明",
            "tanks": [],
            "healers": [],
            "dps": [],
        }

        view = RecruitView(party_data)
        embed = view.create_embed()
        await interaction.response.send_message(embed=embed, view=view)


# 3. 互動按鈕與招募看板邏輯 (View)
class RecruitView(discord.ui.View):
    def __init__(self, data):
        super().__init__(timeout=None)
        self.data = data

    def create_embed(self):
        embed = discord.Embed(
            title=f"⚔️ FF14 隊伍招募：{self.data['title']}",
            description=self.data["desc"],
            color=discord.Color.gold(),
        )
        embed.set_author(
            name=f"隊長：{self.data['leader'].display_name}",
            icon_url=self.data["leader"].display_avatar.url
            if self.data["leader"].display_avatar
            else None,
        )

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

        embed.set_footer(text="點擊下方按鈕即可登記或取消對應職能！")
        return embed

    async def _toggle_role(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
        role_key: str,
        limit: int,
        label_prefix: str,
        role_display: str,
    ):
        user = interaction.user
        target_list = self.data[role_key]

        if user in target_list:
            target_list.remove(user)
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
                if user in self.data[key]:
                    self.data[key].remove(user)
            target_list.append(user)
            await interaction.response.send_message(
                f"✅ 成功登記為 {role_display}！", ephemeral=True
            )

        button.label = f"{label_prefix} ({len(target_list)}/{limit})"
        await interaction.message.edit(embed=self.create_embed(), view=self)

    @discord.ui.button(
        label="＋ 登記 Tank (0/2)",
        style=discord.ButtonStyle.primary,
        custom_id="join_tank",
    )
    async def join_tank(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._toggle_role(
            interaction, button, "tanks", 2, "＋ 登記 Tank", "Tank"
        )

    @discord.ui.button(
        label="＋ 登記 Healer (0/2)",
        style=discord.ButtonStyle.success,
        custom_id="join_healer",
    )
    async def join_healer(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._toggle_role(
            interaction, button, "healers", 2, "＋ 登記 Healer", "Healer"
        )

    @discord.ui.button(
        label="＋ 登記 DPS (0/4)",
        style=discord.ButtonStyle.danger,
        custom_id="join_dps",
    )
    async def join_dps(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._toggle_role(
            interaction, button, "dps", 4, "＋ 登記 DPS", "DPS"
        )


# 4. 註冊斜線指令
@bot.tree.command(name="recruit", description="發布一個新的 FF14 副本或挖寶隊伍招募")
async def recruit_command(interaction: discord.Interaction):
    await interaction.response.send_modal(RecruitModal())


# 5. 啟動機器人（優先讀取環境變數 DISCORD_TOKEN）
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("找不到 DISCORD_TOKEN 環境變數，請先在雲端或系統環境變數中設定。")

bot.run(token)