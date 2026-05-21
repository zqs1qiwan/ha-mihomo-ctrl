<h1 align="center">Homeassistant Mihomo Controller</h1>

<p align="center">
  <img src="assets/logo.png" alt="ha-mihomo-ctrl Logo" width="180" height="180">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=zqs1qiwan&repository=ha-mihomo-ctrl&category=integration" target="_blank">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.">
  </a>
</p>

[English README](#english-readme) | 中文说明

**ha-mihomo-ctrl** 是一个专为 **Home Assistant** 设计的高性能、专业级 Mihomo (Clash) 核心控制器。该集成不包含底层代理实现，专注于通过外部 API 对路由器或服务器上运行的 Mihomo (Clash) Core 进行高效控制、策略切换与物理开关。

---

## 核心技术特性 (Core Features)

1. **零轮询 · WebSocket 异步推流 (`local_push`)**
   同类集成通常采用基于时间间隔的 REST API 轮询机制来获取网速与连接状态，存在延迟且增加了路由器的系统开销。本集成采用 **WebSocket 异步单链接推流**（直接连接 `/traffic` 和 `/connections` 端点），由 Mihomo Core 主动实时推送数据，实现 1 秒级无延迟的速率与连接数刷新，最大程度减少对 Home Assistant 和路由器的 CPU 开销。
2. **优雅重连（指数退避机制）**
   当 OpenClash 订阅更新、重载或路由器重启时，集成会自动进入指数退避（Exponential Backoff）重连状态，避免在 Home Assistant 日志中输出大量无意义的 TCP Traceback 异常，防止阻塞 HA Event Loop 导致界面无响应。连接恢复后将自动重新建立连接。
3. **原生 `Select` 策略组生态**
   集成启动时会自动扫描 Mihomo 下所有的 `Selector`、`Fallback`、`URLTest` 等策略组，并将其映射为标准的 **`select.mihomo_group_[group_name]`** 实体。用户可直接在前端卡片中切换节点，完美契合 Home Assistant 原生生态。
4. **一键延迟测速与穿透挂载**
   为每一个策略组注册一个测速按钮。触发测速后，测速结果将采用双规穿透（Dual-Fallback）算法直接写入对应策略组实体的 `latency` 属性中（即使配置中没有为子物理节点单独做测速记录，也会通过策略组的历史数据自动提取当前选中节点的延迟）。
5. **内嵌 OpenWrt/OpenClash 物理开关 (SSH 联动)**
   本集成不仅控制 Clash 的策略节点，还内嵌了对 OpenWrt (OpenClash) 底层服务的物理开关控制。启用并配置 SSH 凭证后，集成会在后台利用异步非阻塞 Shell 通过 SSH 运行 `uci` 指令来开启或关闭 OpenClash 守护进程。无需手动在 `configuration.yaml` 中配置自定义的 `command_line` 或 `template` 开关。

---

## 安装方法 (Installation)

### 方法 1: 通过 HACS (推荐)
1. 打开 Home Assistant，进入 **HACS** -> **Integrations**。
2. 点击右上角的三个点，选择 **Custom repositories (自定义存储库)**。
3. 输入本仓库地址 `https://github.com/zqs1qiwan/ha-mihomo-ctrl`，类别选择 **Integration**。
4. 添加后在 HACS 列表中搜索 `Mihomo Controller` 并下载，完成后重启 Home Assistant。

### 方法 2: 手动安装
1. 下载本仓库，将 `custom_components/mihomo_ctrl` 文件夹完整拷贝至你 Home Assistant 配置目录的 `custom_components/` 目录下（拷贝后路径应为 `/config/custom_components/mihomo_ctrl/`）。
2. 重启 Home Assistant。

---

## 初始化配置 (Setup & Configuration)

[![点击一键添加集成](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=mihomo_ctrl)

1. 点击上方徽章，或进入 HA 网页端 -> **设置 (Settings)** -> **设备与服务 (Devices & Services)**。
2. 点击右下角 **添加集成 (Add Integration)**，搜索并选择 **`Mihomo Controller`**。
3. 在引导弹窗中，输入参数：
   * **API 控制器地址 (URL)**: 输入你的 Clash 外部控制器 API 端口（例如 `192.168.2.1:9090`）。
   * **秘钥 Bearer Token (Token)**: 输入你的外部控制器密钥（若无请保持留空）。
   * **是否启用 OpenWrt 物理开关**: 如需一站式管理 OpenWrt 上的 OpenClash 运行状态，请勾选它。勾选后可以进一步输入：
     * **SSH 宿主机 IP**: OpenWrt 路由器的 IP 地址（如 `192.168.2.1`）。
     * **SSH 用户名**: 默认 `root`。
     * **SSH 秘钥路径**: 默认 `/config/sshkeys/id_rsa_ha`（你 HA 容器内用于 SSH 免密登录路由器的私钥路径）。
4. 点击 **提交 (Submit)** 完成配置。

---

## Lovelace 看板配置推荐 (Lovelace Dashboard Config)

### 运行效果预览 (Dashboard Preview)

<p align="center">
  <img src="assets/dashboard_demo.jpg" alt="Lovelace Dashboard Demo" width="380">
</p>

为了完美适配这套极简、无延迟、工业级的控制系统，推荐在 **概览 (Overview)** 页面中，点击编辑控制面板，添加一个 **手动 (Manual)**卡片，并覆盖粘贴以下 YAML：

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Mihomo
    show_header_toggle: false
    entities:
      - entity: switch.openclash
        name: 物理总开关 (OpenClash)
        secondary_info: last-changed
      - entity: sensor.mihomo_core_status
        name: 控制器运行状态

  - type: grid
    square: false
    columns: 3
    cards:
      - type: sensor
        entity: sensor.mihomo_download_speed
        name: 下载速度
        graph: line
      - type: sensor
        entity: sensor.mihomo_upload_speed
        name: 上传速度
        graph: line
      - type: sensor
        entity: sensor.mihomo_active_connections
        name: 活跃连接数

  - type: entities
    title: 策略路由
    entities:
      - entity: select.mihomo_proxy
        name: 主代理节点切换
      - entity: button.mihomo_delay_test_proxy
        name: 一键测试主策略节点延迟

  - type: markdown
    title: 分组测速延迟
    content: >-
      {% set group = 'select.mihomo_proxy' %}
      {% set latencies = state_attr(group, 'latency') %}
      {% if latencies %}
      | 节点名称 | 实时延迟 |
      | :--- | :--- |
      {% for node, delay in latencies.items() %}
      {% if delay > 0 %}
      {% if delay < 100 %}
      | {{ node }} | <font color="green">● {{ delay }}ms</font> |
      {% elif delay < 250 %}
      | {{ node }} | <font color="orange">● {{ delay }}ms</font> |
      {% else %}
      | {{ node }} | <font color="red">● {{ delay }}ms</font> |
      {% endif %}
      {% else %}
      | {{ node }} | <font color="gray">● 测速中 / 超时</font> |
      {% endif %}
      {% endfor %}
      {% else %}
      暂无测速数据，请在上方点击「一键测试」按钮。
      {% endif %}
```

---

<div id="english-readme"></div>

<h1 align="center">Homeassistant Mihomo Controller (English)</h1>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=zqs1qiwan&repository=ha-mihomo-ctrl&category=integration" target="_blank">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.">
  </a>
</p>

A high-performance, developer-grade Home Assistant custom integration to monitor and control an external Mihomo (Clash) Core. 

---

## Key Features

1. **Zero-Polling · WebSockets Push (`local_push`)**
   Unlike standard integrations that constantly poll the REST API every 3–5 seconds (causing lag and unnecessary CPU overhead), this integration streams real-time traffic speeds and connection counts via a persistent **WebSocket connection** (`/traffic` and `/connections`). It provides smooth 1-second updates with no Event Loop blockage and minimal CPU load on your router.
2. **Graceful Reconnection (Exponential Backoff)**
   If OpenClash triggers a subscription reload or the router reboots, the integration enters an exponential backoff reconnection state. It reconnects silently without flooding Home Assistant logs with TCP connection Tracebacks or locking up the interface.
3. **Native `Select` Entities Mapping**
   Automatically discovers Mihomo strategy groups (such as `Selector`, `Fallback`, `URLTest`) and maps them to standard **`select.mihomo_group_[group_name]`** entities. Switch nodes directly via Home Assistant's native cards.
4. **On-Demand Delay Testing & Dual-Fallback Mapping**
   Exposes button entities to trigger core-side delay tests for each strategy group. Results are mapped back to the `latency` attribute of the corresponding `select` entity using a dual-fallback algorithm (retrieving latencies from physical nodes or group histories).
5. **Built-in OpenWrt/OpenClash Physical Switch Control (SSH Bridge)**
   Provides direct control over the OpenClash daemon on OpenWrt via SSH. It executes asynchronous non-blocking SSH `uci` commands on your router, eliminating the need to configure custom `command_line` or `template` switches in `configuration.yaml`.

---

## Installation

### Method 1: Via HACS (Recommended)
1. Open Home Assistant -> **HACS** -> **Integrations**.
2. Click the three dots in the top-right -> **Custom repositories**.
3. Add `https://github.com/zqs1qiwan/ha-mihomo-ctrl` as an **Integration**.
4. Search for `Mihomo Controller`, download it, and restart Home Assistant.

### Method 2: Manual
1. Download this repository and copy the `custom_components/mihomo_ctrl` folder into your HA `/config/custom_components/` directory.
2. Restart Home Assistant.

---

## Setup & Configuration

[![Open your Home Assistant instance and start the setup flow of a specific integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=mihomo_ctrl)

1. Settings -> **Devices & Services** -> **Add Integration** -> Search for **`Mihomo Controller`**.
2. Fill out the API details:
   * **API Base URL**: IP:Port of your Clash REST API (e.g., `192.168.2.1:9090`).
   * **Secret Token**: Bearer token (if configured, otherwise keep blank).
   * **Enable OpenWrt Physical Switch**: Check this to control the OpenClash daemon via SSH. Provide the SSH Host, User (`root`), and Path to the Private Key (e.g., `/config/sshkeys/id_rsa_ha`).

---

## License

MIT License. Created by [laobai](https://github.com/zqs1qiwan).
