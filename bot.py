async def apply_job_selection(
        self,
        interaction: discord.Interaction,
        role_key: str,
        chosen_job: str | None,
        board_message: discord.Message,
    ):
        import traceback

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
