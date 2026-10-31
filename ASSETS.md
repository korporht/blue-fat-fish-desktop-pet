# 素材来源与运行方式

本项目素材来自用户提供的 whale-pet 动画包。本次打包保留原始像素，不生成新的角色画面。

- `app/assets/atlas.json` 与三页 `atlas*.png`：原有 1224 帧，包含镜像别名。
- `app/assets/extra/ds_code_eureka`：`whale-pet-frames-code-eureka.zip` 中的无主气泡版本，76 帧。
- `app/assets/extra/ds_tail_allow`：`whale-pet-frames-tail-allow.zip` 中的无文字版本，60 帧；`source.json` 记录原始 ZIP 和各 PNG 的 SHA-256。
- `app/assets/extra/additions.json`：吃饱揉肚子及游泳，共 257 张原始透明 PNG（小尺寸帧仅存档）；完整尺寸的左右向由 swim-full 两个素材卷合并，保留 10 fps、转向、点击跃出和逐帧 SHA-256。
- `app/assets/extra/activities.json`：竹蜻蜓、扫地、吹泡泡三套新增素材，共 197 张原始 RGBA PNG；记录三个 ZIP 与逐帧 SHA-256、10 fps、画布和对齐偏移。竹蜻蜓与扫地按源包推荐片段组合成有限时完整动作。
- `app/assets/extra/ds_lion_dance`：舞狮头，241 张 RGBA PNG（24 fps、画布 480×270、offset [112,3]，源为 640×360 等比 0.75 缩放并按 alpha 阈值 8 清除 VP9 压缩噪声）。

**舞狮头素材的授权隔离（与上面各项不同）**：`ds_lion_dance` 的帧转自 `@luweiyabo/dsh-whale-pet@0.1.3` 包内
`assets/thumb/festivals/lion_dance.webm`（sha256 `6d2006b4023d44087cf4c7dc055d1d8f2a8cec32e22610807a2dfea7bb0dc367`，
tgz sha256 `56418f614b2858bce3e769fb4fdef7a4be54298c614a5b97db6a7cdf2fdb0663`）。该插件的动画素材来自
`PC2005-cloud/dsh-pet`，按其第三方资源条款**仅允许非商业使用**，不在本仓库 MIT 代码授权或 CC BY-NC-SA 素材授权范围内。
本机个人使用；再分发或改编前请核对上游最新条款。`activities.json` 的 `sources` 字段记录了同一溯源信息。
- 对话气泡由程序实时绘制，可关闭。摸尾巴的确认和超时片段独立，不会串播。
- `docs/previews/tail-allow.png`：应用实际渲染的分支预览。

原始素材 ZIP、生成原画和本机运行环境没有重复放入仓库。
