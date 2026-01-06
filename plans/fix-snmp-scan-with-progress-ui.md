# fix: SNMP 扫描功能修复与进度 UI 实现

## 概述

修复 SNMP 设备扫描功能，当前点击"开始扫描"按钮时显示浏览器 alert 弹窗并返回 500 错误。需要实现完整的扫描进度界面，包括实时进度条、扫描日志和成功/失败状态显示。

## 问题分析

### 当前问题

1. **API 端点缺失**：前端调用的 API 未实现
   - `/api/network-devices/{id}/scan/` - 404 错误
   - `/api/agent/scan_all/` - 404 错误

2. **前端使用 alert() 弹窗**：用户体验差
   - `device_list.html:507-523` - 使用 `alert()` 显示状态

3. **无进度反馈**：用户无法知道扫描进度

### 根本原因

- `views.py` 中 `NetworkDeviceViewSet` 缺少 `scan` action
- `views.py` 中 `AgentViewSet` 缺少 `scan_all` action
- 前端缺少进度弹窗组件

## 技术方案

### 架构决策

| 决策项 | 选择 | 理由 |
|-------|------|------|
| 单设备扫描 | 同步执行 | 耗时短(5-10秒)，简单直接 |
| 批量扫描 | 异步执行 + 轮询 | 耗时长，需要进度反馈 |
| 进度存储 | Redis Cache | 快速读写，自动过期 |
| 进度获取 | 短轮询 (2秒) | 简单可靠，无需额外依赖 |

### 数据流

```
单设备扫描:
  用户点击 → POST /api/network-devices/{id}/scan/
           → 同步执行 SNMPScanner
           → 返回结果 JSON
           → 更新 UI

批量扫描:
  用户点击 → POST /api/agent/scan_all/
           → 创建 Django-Q 任务
           → 返回 task_id
           → 前端开始轮询
           → GET /api/agent/scan_status/?task_id=xxx
           → 更新进度条和日志
           → 任务完成后显示摘要
```

## 实现计划

### Phase 1: 后端 API 实现

#### 1.1 单设备扫描 API

**文件**: `/opt/ipim/backend/ipam/views.py`

```python
# NetworkDeviceViewSet 添加 scan action

@extend_schema(
    summary="扫描单个网络设备",
    description="触发 SNMP 扫描并返回扫描结果",
    responses={200: {"type": "object", "properties": {
        "status": {"type": "string"},
        "scanned": {"type": "integer"},
        "updated": {"type": "integer"},
        "conflicts": {"type": "integer"},
        "elapsed": {"type": "number"},
    }}},
    tags=["Network Device"],
)
@action(detail=True, methods=["post"])
def scan(self, request: Request, pk: int = None) -> Response:
    """扫描单个设备"""
    device = self.get_object()

    if not device.enabled:
        # 允许扫描禁用设备，但记录警告
        pass

    try:
        from .snmp_scanner import SNMPScanner
        import time

        start_time = time.time()
        scanner = SNMPScanner(device)
        scanned, updated, conflicts = scanner.scan_and_update()
        elapsed = time.time() - start_time

        return Response({
            "status": "success",
            "device": device.name,
            "scanned": scanned,
            "updated": updated,
            "conflicts": conflicts,
            "elapsed": round(elapsed, 2),
        })
    except Exception as e:
        device.last_scan_status = "error"
        device.last_scan_error = str(e)[:500]
        device.save()

        return Response({
            "status": "error",
            "device": device.name,
            "error": str(e),
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
```

#### 1.2 批量扫描 API

**文件**: `/opt/ipim/backend/ipam/views.py`

```python
# AgentViewSet 添加 scan_all 和 scan_status actions

@extend_schema(
    summary="扫描所有网络设备",
    description="启动异步任务扫描所有启用的设备",
    responses={202: {"type": "object", "properties": {
        "task_id": {"type": "string"},
        "status": {"type": "string"},
        "device_count": {"type": "integer"},
    }}},
    tags=["Agent"],
)
@action(detail=False, methods=["post"])
def scan_all(self, request: Request) -> Response:
    """扫描所有设备"""
    from django_q.tasks import async_task
    from .models import NetworkDevice

    # 获取启用的设备数量
    device_count = NetworkDevice.objects.filter(enabled=True).count()

    if device_count == 0:
        return Response({
            "status": "error",
            "error": "没有启用的设备可供扫描",
        }, status=status.HTTP_400_BAD_REQUEST)

    # 创建异步任务
    task_id = async_task(
        'ipam.tasks.scan_all_with_progress',
        group='snmp_scan',
        cached=True
    )

    return Response({
        "task_id": task_id,
        "status": "queued",
        "device_count": device_count,
    }, status=status.HTTP_202_ACCEPTED)

@extend_schema(
    summary="查询扫描任务状态",
    description="获取扫描任务的进度和结果",
    parameters=[
        OpenApiParameter(name="task_id", type=str, required=True),
    ],
    responses={200: {"type": "object"}},
    tags=["Agent"],
)
@action(detail=False, methods=["get"])
def scan_status(self, request: Request) -> Response:
    """查询扫描状态"""
    task_id = request.query_params.get('task_id')
    if not task_id:
        return Response({"error": "task_id is required"}, status=400)

    from django.core.cache import cache
    from django_q.tasks import fetch

    # 尝试从缓存获取进度
    progress = cache.get(f'scan_progress_{task_id}')

    if progress:
        return Response(progress)

    # 尝试从 Django-Q 获取任务结果
    task = fetch(task_id, cached=True)

    if task is None:
        return Response({
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "message": "任务排队中...",
        })

    if task.success:
        return Response({
            "task_id": task_id,
            "status": "completed",
            "progress": 100,
            "result": task.result,
        })
    else:
        return Response({
            "task_id": task_id,
            "status": "failed",
            "progress": 100,
            "error": str(task.result),
        })
```

#### 1.3 异步任务修改

**文件**: `/opt/ipim/backend/ipam/tasks.py`

```python
def scan_all_with_progress() -> Dict[str, Any]:
    """带进度报告的批量扫描任务"""
    from django.core.cache import cache
    from django_q.tasks import current_task
    from .snmp_scanner import SNMPScanner
    from .models import NetworkDevice
    import time

    task_id = current_task()
    devices = list(NetworkDevice.objects.filter(enabled=True))
    total = len(devices)

    results = {
        "total_devices": total,
        "successful": 0,
        "failed": 0,
        "total_scanned": 0,
        "total_updated": 0,
        "total_conflicts": 0,
        "errors": [],
        "logs": [],
    }

    start_time = time.time()

    for idx, device in enumerate(devices, 1):
        # 更新进度
        progress_data = {
            "task_id": task_id,
            "status": "running",
            "progress": int((idx - 1) / total * 100),
            "current": idx,
            "total": total,
            "current_device": device.name,
            "message": f"正在扫描 {device.name}...",
            "logs": results["logs"][-20:],  # 最近20条日志
            "partial_results": {
                "successful": results["successful"],
                "failed": results["failed"],
                "total_scanned": results["total_scanned"],
            },
        }
        cache.set(f'scan_progress_{task_id}', progress_data, timeout=3600)

        try:
            scanner = SNMPScanner(device)
            scanned, updated, conflicts = scanner.scan_and_update()

            results["successful"] += 1
            results["total_scanned"] += scanned
            results["total_updated"] += updated
            results["total_conflicts"] += conflicts

            log_entry = {
                "time": time.strftime("%H:%M:%S"),
                "level": "success",
                "device": device.name,
                "message": f"发现 {scanned} 条 ARP，更新 {updated} 个 IP",
            }
            results["logs"].append(log_entry)

        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "device": device.name,
                "ip": device.ip_address,
                "error": str(e),
            })

            log_entry = {
                "time": time.strftime("%H:%M:%S"),
                "level": "error",
                "device": device.name,
                "message": str(e)[:100],
            }
            results["logs"].append(log_entry)

    results["elapsed_seconds"] = round(time.time() - start_time, 2)

    # 最终进度
    cache.set(f'scan_progress_{task_id}', {
        "task_id": task_id,
        "status": "completed",
        "progress": 100,
        "result": results,
    }, timeout=3600)

    return results
```

### Phase 2: 前端进度弹窗

#### 2.1 扫描进度弹窗组件

**文件**: `/opt/ipim/backend/templates/ipam/device_list.html`

在模板末尾添加扫描进度弹窗：

```html
<!-- 扫描进度弹窗 -->
<div x-data="scanProgress()"
     x-show="isOpen"
     x-cloak
     class="fixed inset-0 z-50 overflow-y-auto"
     @scan-device.window="startSingleScan($event.detail.id, $event.detail.name)"
     @scan-all.window="startBatchScan()">

    <!-- 背景遮罩 -->
    <div class="fixed inset-0 bg-black/50 transition-opacity" @click="closeIfCompleted()"></div>

    <!-- 弹窗内容 -->
    <div class="flex min-h-full items-center justify-center p-4">
        <div class="relative w-full max-w-lg rounded-xl border overflow-hidden
                    bg-white border-slate-200 dark:bg-slate-800 dark:border-slate-700
                    shadow-2xl transform transition-all">

            <!-- 标题栏 -->
            <div class="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
                <h3 class="text-lg font-semibold text-slate-900 dark:text-white">
                    <span x-text="title"></span>
                </h3>
                <button @click="closeIfCompleted()"
                        class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                        :class="{'opacity-50 cursor-not-allowed': status === 'running'}">
                    <span class="material-symbols-outlined">close</span>
                </button>
            </div>

            <!-- 进度区域 -->
            <div class="p-6 space-y-4">
                <!-- 进度条 -->
                <div>
                    <div class="flex justify-between text-sm mb-2">
                        <span class="text-slate-600 dark:text-slate-400" x-text="message"></span>
                        <span class="font-medium text-slate-900 dark:text-white" x-text="progress + '%'"></span>
                    </div>
                    <div class="w-full h-3 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                        <div class="h-full rounded-full transition-all duration-300"
                             :class="{
                                 'bg-blue-500': status === 'running',
                                 'bg-emerald-500': status === 'completed',
                                 'bg-red-500': status === 'failed'
                             }"
                             :style="{ width: progress + '%' }">
                        </div>
                    </div>
                </div>

                <!-- 统计信息 -->
                <div x-show="isBatch" class="grid grid-cols-3 gap-3 text-center">
                    <div class="p-3 rounded-lg bg-slate-100 dark:bg-slate-700/50">
                        <div class="text-2xl font-bold text-slate-900 dark:text-white" x-text="stats.total"></div>
                        <div class="text-xs text-slate-500">总计</div>
                    </div>
                    <div class="p-3 rounded-lg bg-emerald-50 dark:bg-emerald-500/10">
                        <div class="text-2xl font-bold text-emerald-600" x-text="stats.success"></div>
                        <div class="text-xs text-slate-500">成功</div>
                    </div>
                    <div class="p-3 rounded-lg bg-red-50 dark:bg-red-500/10">
                        <div class="text-2xl font-bold text-red-600" x-text="stats.failed"></div>
                        <div class="text-xs text-slate-500">失败</div>
                    </div>
                </div>

                <!-- 实时日志 -->
                <div x-show="isBatch">
                    <div class="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">扫描日志</div>
                    <div class="h-48 overflow-y-auto rounded-lg bg-slate-900 p-3 font-mono text-xs"
                         x-ref="logContainer">
                        <template x-for="log in logs" :key="log.time + log.device">
                            <div class="mb-1">
                                <span class="text-slate-500" x-text="'[' + log.time + ']'"></span>
                                <span :class="{
                                    'text-emerald-400': log.level === 'success',
                                    'text-red-400': log.level === 'error',
                                    'text-blue-400': log.level === 'info'
                                }" x-text="log.device + ': ' + log.message"></span>
                            </div>
                        </template>
                    </div>
                </div>

                <!-- 完成状态 -->
                <div x-show="status === 'completed'"
                     class="p-4 rounded-lg bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30">
                    <div class="flex items-center gap-3">
                        <span class="material-symbols-outlined text-3xl text-emerald-600">check_circle</span>
                        <div>
                            <div class="font-semibold text-emerald-800 dark:text-emerald-400">扫描完成</div>
                            <div class="text-sm text-slate-600 dark:text-slate-400" x-text="resultSummary"></div>
                        </div>
                    </div>
                </div>

                <!-- 失败状态 -->
                <div x-show="status === 'failed'"
                     class="p-4 rounded-lg bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30">
                    <div class="flex items-center gap-3">
                        <span class="material-symbols-outlined text-3xl text-red-600">error</span>
                        <div>
                            <div class="font-semibold text-red-800 dark:text-red-400">扫描失败</div>
                            <div class="text-sm text-slate-600 dark:text-slate-400" x-text="errorMessage"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 底部按钮 -->
            <div class="px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex justify-end gap-3">
                <button x-show="status === 'completed' || status === 'failed'"
                        @click="close()"
                        class="px-4 py-2 rounded-lg text-sm font-medium transition-colors
                               bg-slate-200 hover:bg-slate-300 text-slate-700
                               dark:bg-slate-700 dark:hover:bg-slate-600 dark:text-white">
                    关闭
                </button>
                <button x-show="status === 'completed'"
                        @click="close(); location.reload();"
                        class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition-colors">
                    刷新列表
                </button>
            </div>
        </div>
    </div>
</div>
```

#### 2.2 扫描进度 JavaScript

```javascript
function scanProgress() {
    return {
        isOpen: false,
        isBatch: false,
        title: '扫描设备',
        status: 'idle', // idle, running, completed, failed
        progress: 0,
        message: '',
        taskId: null,
        pollTimer: null,
        logs: [],
        stats: { total: 0, success: 0, failed: 0 },
        resultSummary: '',
        errorMessage: '',

        // 单设备扫描
        async startSingleScan(deviceId, deviceName) {
            this.reset();
            this.isOpen = true;
            this.isBatch = false;
            this.title = `扫描设备: ${deviceName}`;
            this.status = 'running';
            this.message = '正在扫描...';
            this.progress = 50;

            try {
                const response = await fetch(`/api/network-devices/${deviceId}/scan/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCsrfToken()
                    }
                });

                const data = await response.json();

                if (response.ok && data.status === 'success') {
                    this.status = 'completed';
                    this.progress = 100;
                    this.resultSummary = `发现 ${data.scanned} 条 ARP，更新 ${data.updated} 个 IP，${data.conflicts} 个冲突`;
                } else {
                    this.status = 'failed';
                    this.progress = 100;
                    this.errorMessage = data.error || '扫描失败';
                }
            } catch (error) {
                this.status = 'failed';
                this.progress = 100;
                this.errorMessage = error.message;
            }
        },

        // 批量扫描
        async startBatchScan() {
            this.reset();
            this.isOpen = true;
            this.isBatch = true;
            this.title = '扫描所有设备';
            this.status = 'running';
            this.message = '正在启动扫描任务...';

            try {
                const response = await fetch('/api/agent/scan_all/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCsrfToken()
                    }
                });

                const data = await response.json();

                if (response.ok && data.task_id) {
                    this.taskId = data.task_id;
                    this.stats.total = data.device_count;
                    this.startPolling();
                } else {
                    this.status = 'failed';
                    this.errorMessage = data.error || '启动扫描失败';
                }
            } catch (error) {
                this.status = 'failed';
                this.errorMessage = error.message;
            }
        },

        // 轮询任务状态
        startPolling() {
            this.pollTimer = setInterval(async () => {
                await this.checkStatus();
            }, 2000); // 每2秒轮询
        },

        async checkStatus() {
            try {
                const response = await fetch(`/api/agent/scan_status/?task_id=${this.taskId}`);
                const data = await response.json();

                this.progress = data.progress || 0;
                this.message = data.message || '';

                if (data.logs) {
                    this.logs = data.logs;
                    this.scrollLogToBottom();
                }

                if (data.partial_results) {
                    this.stats.success = data.partial_results.successful || 0;
                    this.stats.failed = data.partial_results.failed || 0;
                }

                if (data.status === 'completed') {
                    this.stopPolling();
                    this.status = 'completed';
                    const r = data.result || {};
                    this.stats.success = r.successful || 0;
                    this.stats.failed = r.failed || 0;
                    this.resultSummary = `共扫描 ${r.total_scanned || 0} 条 ARP，更新 ${r.total_updated || 0} 个 IP，耗时 ${r.elapsed_seconds || 0} 秒`;
                } else if (data.status === 'failed') {
                    this.stopPolling();
                    this.status = 'failed';
                    this.errorMessage = data.error || '扫描任务失败';
                }
            } catch (error) {
                console.error('轮询失败:', error);
            }
        },

        stopPolling() {
            if (this.pollTimer) {
                clearInterval(this.pollTimer);
                this.pollTimer = null;
            }
        },

        scrollLogToBottom() {
            this.$nextTick(() => {
                if (this.$refs.logContainer) {
                    this.$refs.logContainer.scrollTop = this.$refs.logContainer.scrollHeight;
                }
            });
        },

        closeIfCompleted() {
            if (this.status !== 'running') {
                this.close();
            }
        },

        close() {
            this.stopPolling();
            this.isOpen = false;
        },

        reset() {
            this.status = 'idle';
            this.progress = 0;
            this.message = '';
            this.taskId = null;
            this.logs = [];
            this.stats = { total: 0, success: 0, failed: 0 };
            this.resultSummary = '';
            this.errorMessage = '';
        },

        getCsrfToken() {
            return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                   document.cookie.split('; ')
                       .find(row => row.startsWith('csrftoken='))
                       ?.split('=')[1] || '';
        }
    };
}
```

#### 2.3 修改扫描按钮事件

**文件**: `/opt/ipim/backend/templates/ipam/device_list.html`

将原来的 `scanDevice()` 和 `scanAllDevices()` 函数改为触发自定义事件：

```javascript
// 替换原来的 scanDevice 函数
function scanDevice(id, name) {
    window.dispatchEvent(new CustomEvent('scan-device', {
        detail: { id: id, name: name }
    }));
}

// 替换原来的 scanAllDevices 函数
function scanAllDevices() {
    if (confirm('确定要扫描所有设备吗？这可能需要几分钟时间。')) {
        window.dispatchEvent(new CustomEvent('scan-all'));
    }
}
```

修改设备行中的扫描按钮：

```html
<!-- 原来的 -->
<button onclick="scanDevice({{ device.id }})" ...>

<!-- 改为 -->
<button @click="scanDevice({{ device.id }}, '{{ device.name }}')" ...>
```

### Phase 3: 测试用例

#### 3.1 单设备扫描测试

```python
# test_scan.py
def test_single_device_scan():
    """测试单设备扫描 API"""
    response = client.post('/api/network-devices/1/scan/')
    assert response.status_code == 200
    data = response.json()
    assert 'status' in data
    assert 'scanned' in data
    assert 'updated' in data
```

#### 3.2 批量扫描测试

```python
def test_batch_scan():
    """测试批量扫描 API"""
    # 启动扫描
    response = client.post('/api/agent/scan_all/')
    assert response.status_code == 202
    data = response.json()
    assert 'task_id' in data

    # 查询状态
    task_id = data['task_id']
    response = client.get(f'/api/agent/scan_status/?task_id={task_id}')
    assert response.status_code == 200
```

## 验收标准

### 功能验收

- [ ] 单设备扫描：点击后显示进度弹窗，完成后显示结果
- [ ] 批量扫描：点击后显示进度弹窗，实时更新进度和日志
- [ ] 进度条正确显示百分比
- [ ] 日志区域实时滚动显示扫描信息
- [ ] 成功/失败状态正确显示
- [ ] 关闭弹窗后可刷新列表

### 错误处理

- [ ] SNMP 超时正确显示错误信息
- [ ] 认证失败正确显示错误信息
- [ ] 网络断开时轮询不崩溃
- [ ] 设备禁用时可以手动扫描

### UI/UX

- [ ] 弹窗在暗色模式下正确显示
- [ ] 进度条动画平滑
- [ ] 日志区域可滚动
- [ ] 关闭按钮在扫描中时禁用

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `views.py` | 修改 | 添加 scan, scan_all, scan_status actions |
| `tasks.py` | 修改 | 添加 scan_all_with_progress 函数 |
| `device_list.html` | 修改 | 添加进度弹窗组件和 JavaScript |

## 依赖

- Django-Q2 (已安装)
- Redis (已配置)
- Alpine.js (已使用)

## 风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Redis 不可用 | 低 | 高 | 添加 Redis 健康检查 |
| 任务队列满 | 低 | 中 | 限制并发扫描任务数 |
| SNMP 扫描超时 | 中 | 低 | 已有超时处理 |

## 参考资料

- Django-Q2 文档: https://django-q2.readthedocs.io/
- Alpine.js 文档: https://alpinejs.dev/
- PySNMP 文档: https://pysnmp.readthedocs.io/

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
