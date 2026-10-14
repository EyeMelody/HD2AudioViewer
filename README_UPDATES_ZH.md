# HD2AudioViewer 0.1.0

启动 audio_modder.exe，请保留同目录下的全部资源文件夹。沿用原项目的单文件程序加外置资源打包结构。

“关于 → 检查软件更新”显示本分支版本、GitHub 地址、原作者及致谢。发现新版后出现按钮，点击在浏览器中打开发布页，由用户下载新版完整包。

“关于 → 检查数据库更新”显示本地 SQLite user_version 和数据库仓库，发现新版后可打开发布页。不会自动覆盖数据库。

启动后后台分别检查两种版本，不阻塞界面。每次请求设置 6 秒网络超时；出错不弹出打断操作的窗口，可从关于菜单查看结果并重试。使用系统/环境代理配置。没有可访问的 Release、网络失败和访问受限均不会显示“已是最新”。

软件发布目标：https://github.com/EyeMelody/HD2AudioViewer
当前版本：0.1.0。后续以 v0.2.0 等更高版本正式 Release 标签发布，检查即可识别。

数据库：https://github.com/raidingforpants/helldivers_audio_db
原作者：RaidingForPants (Evelyn)，https://github.com/RaidingForPants
原项目：https://github.com/RaidingForPants/hd2-audio-modder
感谢原作者及所有贡献者提供解析、界面和音频数据库基础。许可证随包保留。

保留只读浏览、补丁对照高亮和音频试听；不提供音频编辑、保存、导出或补丁写入。
