# HD2AudioViewer

基于 [RaidingForPants/hd2-audio-modder](https://github.com/RaidingForPants/hd2-audio-modder) 的中文只读音频模组预览版，保留原项目布局、资源浏览、补丁对照高亮和试听功能。

## 下载与使用

从 [Releases](https://github.com/EyeMelody/HD2AudioViewer/releases) 下载 `HD2AudioViewer-0.1.0.zip`，完整解压并运行 `audio_modder.exe`。首次使用在“选项”中选择游戏 `data` 目录，再拖入 `.patch_0` 文件。

保留程序旁的 `theme`、`vgmstream-win64`、`ui_assets` 等资源。高亮表示与当前原版字节不同，也可能包含音频头变化，不等于全部是新配音。

“关于”提供软件和数据库更新检查。启动时异步检查，网络异常不会阻塞操作；更新按钮打开发布页，不自动安装。

## 从源码运行和打包

当前发行包针对 Windows x64，构建验证环境为 Python 3.12（带 Tk）。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-viewer.txt
.venv/Scripts/python original_readonly.py
```

运行前需从 [音频数据库发布页](https://github.com/raidingforpants/helldivers_audio_db/releases) 获取 `friendlynames.db`，从 [vgmstream](https://github.com/vgmstream/vgmstream/releases) 获取 Windows 工具并解压为 `vgmstream-win64`。也可复用本分支发行包内的这两项资源，放到源码根目录。

```powershell
.venv/Scripts/python -m unittest test_updates test_original_readonly -v
.venv/Scripts/python package_viewer.py release-010
```

打包脚本要求新的输出后缀，保留已有产物。真实游戏补丁测试需要通过 `HD2_TEST_PATCH` 和 `HD2_TEST_GAME_DATA` 环境变量提供对应的测试样本，否则跳过该测试。生成文件的维护入口为 `build_original_readonly.py`，界面控制器为 `readonly_ui.py`。

## 致谢与许可证

感谢原作者 [RaidingForPants (Evelyn)](https://github.com/RaidingForPants)、原项目贡献者、HD2SDK 社区和音频数据库维护者。本仓库保留 Fork 关系、上游提交历史及 [MIT 许可证](LICENSE)。本分支不是原作者的官方发行版。

下方保留上游原始说明，仅适用于源码中保留的原版编辑器；本分支应运行 `original_readonly.py`。

---

## 上游原始说明：Audio and Text Modder For Helldivers 2

I made this program to help make modding audio data easier.

[Mini tutorial for audio modding](https://docs.google.com/document/d/e/2PACX-1vT5mFXlk0iPGF-yoR3hMPrws3iPa4cY5O6PjzLcgz3Jj9vHUh5mYN1P1uWb6QiPA8K5rcvac929icV2/pub)

Thanks to everyone behind the [Helldivers 2 Blender Addon](https://github.com/Boxofbiscuits97/HD2SDK-CommunityEdition) for letting me use some of their code.

You can use the prebuilt executables (built with PyInstaller) in the releases tab, or you can run the Python.

If you run the Python code, you will need the appropriate distribution of [vgmstream](https://vgmstream.org/) to play audio from within the program. Place the vgmstream folder into the same folder as the Python code.

## Running the Python code

Requires Python 3.10 or later.

### Windows
Install [Python 3](https://www.python.org/downloads/windows/). Make sure to check in the Python installer the optional feature "tcl/tk and IDLE".

Install the dependencies:

```python -m pip install -r requirements.txt```

Run the program:

```python audio_modder.py```

### Linux
PortAudio and tkinter must be installed.

**Ubuntu:**

```apt-get install python3-tk```

```apt-get install portaudio19-dev python-all-dev```


Install the dependencies:

```python3 -m pip install -r requirements.txt```

Run the program:

```python3 audio_modder.py```


### MacOS
PortAudio and Python must be installed.

**Python**

Install [Python](https://www.python.org/downloads/macos/).

**PortAudio**

Install [Homebrew package manager](https://brew.sh/).

Install portaudio:

```brew install portaudio```



Install the dependencies:

```python3 -m pip install -r requirements.txt```

Run the program:

```python3 audio_modder.py```
