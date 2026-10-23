# 叙幕 · 中文剧情剧本工作台 0.2

Windows / macOS 桌面应用源码工程。导入视频，通过本地或云端模型分析，生成场景、动作、对白格式的中文剧本草稿，编辑后导出 DOCX / PDF。当前交付为源码与验证示例；Windows/macOS 安装包尚未构建、实测。

[界面](docs/desktop-preview.png) · [验证记录](docs/validation.md) · [技术测试剧本 PDF](docs/examples/技术测试剧本.pdf) · [DOCX](docs/examples/技术测试剧本.docx)

## 安装与启动

需要 Python 3.11+、FFmpeg（ffmpeg / ffprobe 在 PATH）、中文字体。

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS: source .venv/bin/activate
pip install -e .
dramascript
```

### 云端

在软件中填写兼容 OpenAI 的服务地址、图像模型和转写模型。默认示例为 gpt-4.1 / whisper-1，不代表账户拥有模型访问权限。转写接口请求 verbose_json 获取片段时间；若服务只返回文本，声音位置会标记待核实。

密钥在软件中输入，或通过安全环境配置注入 DRAMASCRIPT_API_KEY，仅保存在进程内存。不要写入代码、项目或聊天。云端模式会向所填服务上传音频、抽样画面与文本，并可能产生费用。远程地址必须为 HTTPS，不允许在 URL 中包含密钥、用户密码或查询参数。

### 本地 Ollama

```sh
pip install -e ".[local]"
# 先安装并启动官方 Ollama
ollama pull qwen2.5vl:7b
```

软件选择“本地”，地址 http://localhost:11434/v1，填写已安装的视觉模型名称。Whisper 默认 small、CPU/int8；首次下载模型联网，缓存后可离线运行。本地模式只连接回环地址，不能伪装成本地向远程服务上传。

当前开发机器未完成 Ollama 权重下载，因此该路径尚无真实推理通过记录。已验证的是下述 Transformers 替代路径。

### 本地 Transformers（可选源码服务）

```sh
# CPU 机器先安装官方 CPU 版，避免下载 CUDA 依赖
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[local,vision]"
python scripts/serve_local_transformers.py --model Qwen/Qwen3-VL-2B-Instruct --revision 89644892e4d85e24eaac8bacfd4f463576704203 --port 11436 --dtype bfloat16 --max-new-tokens 2048
```

在软件选择“本地”，地址改为 http://localhost:11436/v1，模型填 Qwen/Qwen3-VL-2B-Instruct，转写模型可填 tiny、small 或已缓存模型的目录。CPU 推理较慢；资源需求取决于模型，建议至少 16GB 内存。若机器不适合 bfloat16，可选 float32。

服务仅监听 127.0.0.1，只接收内嵌图像，使用 safetensors，不执行模型仓库自定义代码。默认 SmolVLM 只适合图像链路诊断。该可选服务以源码提供，未捆绑进桌面包；桌面包通过本机兼容接口调用它。

## 使用与输出

1. 选择视频及新的空项目文件夹；打开旧项目则使用“打开已有项目”。程序不会覆盖无项目标识的非空目录。
2. 选择分析模式、模型并开始。每 120 秒处理一段，每 10 秒抽帧，另补充最多 12 张场景变化帧。暂停在当前请求结束后生效，已翻译语句和已完成片段可复用。
3. 查看中文剧本及对应证据；选择片段或输入秒数提取画面，使用系统播放器核对完整动作。
4. 运行“全片剧情复核 / 人物档案”。时间顺序与声音清单由项目证据直接生成；模型仅提取待核实姓名/性格倾向和核对项目，必须能关联实际证据。报告不会覆盖剧本正文。
5. 编辑剧本，保存修订稿，导出 DOCX / PDF。自动草稿和人工修订稿分别保存。

项目保存视频路径、抽帧、音频、转写、译文、场景证据与报告，不保存 API 密钥。项目目录应保存在受保护位置，不应提交到 Git。

## 当前证据流程 v4

原始语音逐条独立译成中文；视觉模型仅接收图片和此前视觉状态，返回场景、静态描述和带时间动作。程序校验场景覆盖、动作时间与帧证据引用，再按时间组合动作和译文。每条译文只出现一次，写作模型不再二次改写或删除对白。静态画面允许没有动作，但必须有画面描述。

旧版本项目可以打开编辑；新版分析需要新目录，以免把旧结果当作新流程复用。输出被接口标记截断、缺少有效中文或包含未翻译的长外语句子时，不标记该片段完成。图像完全重复时合并上传，但保留采样时间，并明确采样间隙内容未知。

人物线索中的引用由程序从证据原样取出。姓名必须在关联证据中出现；未明确的人物保留“未识别声音”。引用省略时，仅在证据来源唯一的情况下关联，并标记仍待核实。模型不能自行改写报告时间、断言无声、虚构历史来源或把推断当确认事实。

## 尚未完成的质量验收

- 尚未用真实长片、多人物对话和复杂无对白动作验收剧情完整性、因果关系与人物持续跟踪。
- 没有专用声纹分离或声画身份自动匹配，对白默认说话人待核实；姓名提及不等于说话人归属。
- 抽样可能遗漏短暂事件，动作时间有估计误差；台词位置与动作前后仍需对照原片。
- 人物性格是带证据的候选推断，跨批次关系、因果和剧情连贯性没有自动通过保证。
- 当前云端没有实际推理记录：开发环境尚未配置密钥。

已通过的技术测试不能替代上述质量验收。示例使用纯蓝色画面与公开测试语音，不是剧情片测试。

## 开发验证与打包

```sh
pip install -e ".[test,local,build]"
pytest
python scripts/build_desktop.py
python scripts/package_source.py
```

分别在目标 Windows/macOS 系统构建；PyInstaller 不交叉编译。构建脚本会检查冻结程序启动，并生成 Windows ZIP 或 macOS DMG。构建机需要 FFmpeg；生成的软件包自带 FFmpeg/FFprobe，并在清空 PATH 后检查组件启动，用户无需另行安装。包未签名，正式分发仍需签名/公证及实机验证。GitHub Actions 双平台流程已保存，尚未执行。

本地转写依赖限制 PyAV <17，避免已复现的 PyAV 19 解码参数不兼容。当前 Linux 构建仅验证该平台，不代表 Windows/macOS 已通过。

实际模型验证可运行：

```sh
python scripts/validate_models.py --mode local --url http://localhost:11436/v1 --model Qwen/Qwen3-VL-2B-Instruct --audio-model tiny --video /path/to/video.mp4 --project /path/to/new-empty-project --review
python scripts/validate_models.py --mode cloud --video /path/to/video.mp4 --project /path/to/another-empty-project --review
```

继续失败任务需加 --resume；缓存复用不能证明本次重新调用了所有模型。real-validation.json 只记录流程完成，始终不自动认定故事质量合格。Windows 路径可用引号括起。

桌面启动、密钥填写及双击构建说明见 [桌面版使用说明](docs/桌面版使用说明.md)。构建不需要密钥；大型本地模型单独下载。
