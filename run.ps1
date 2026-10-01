# -*- coding: utf-8 -*-
"""
run.ps1 — 一键运行 AutoFillFace
自动定位已装依赖的 Python（优先豆包运行时，其次系统 python），
缺依赖时用清华源自动安装，然后启动程序。

用法：
  powershell -ExecutionPolicy Bypass -File run.ps1            # 启动
  powershell -ExecutionPolicy Bypass -File run.ps1 --selftest # 自检
"""
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---- 定位 Python（优先已安装的完整版，其次豆包运行时）----
$knownPython = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
$py = $null
if (Test-Path $knownPython) {
    $py = $knownPython
} elseif (Test-Path "C:\Users\zhaow\AppData\Local\Doubao\User Data\sandbox_runtime\bases\9f6d27f23933fb44a3a1c728c88a5ce4\python\python.exe") {
    $py = "C:\Users\zhaow\AppData\Local\Doubao\User Data\sandbox_runtime\bases\9f6d27f23933fb44a3a1c728c88a5ce4\python\python.exe"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $py = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $py = "py"
}
if (-not $py) {
    Write-Host "[错误] 未找到 Python。请先安装 Python 3.10+（https://www.python.org/downloads/），然后重新运行本脚本。"
    exit 1
}
Write-Host "[ok] 使用 Python: $py"

# ---- 检查依赖 ----
& $py -c "import mss, cv2, numpy, PIL, pynput, requests" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[..] 依赖缺失，正在用清华源安装（首次约 1-3 分钟）..."
    & $py -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r "$root\requirements.txt"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 依赖安装失败，请检查网络后重试。"
        exit 1
    }
    Write-Host "[ok] 依赖安装完成"
}

# ---- 启动 ----
Set-Location $root
if ($args.Count -gt 0) {
    & $py "$root\app\main.py" @args
} else {
    & $py "$root\app\main.py"
}
