# -*- coding: utf-8 -*-
"""
build.ps1 — 一键打包脚本（清华源 + 备份 + PyInstaller）
用法：powershell -ExecutionPolicy Bypass -File build.ps1
产物：dist\AutoFillFace.exe
"""
$ErrorActionPreference = "Stop"
$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 定位 Python：优先官方完整版（含 Tcl/Tk），其次豆包运行时
$py = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "== 0/3 使用 Python: $py =="

Write-Host "== 1/3 备份当前状态 =="
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bak = Join-Path $root "backups\backup_$stamp.zip"
$items = Get-ChildItem $root -Exclude backups,.tmp_ref,build,dist | ForEach-Object { $_.FullName }
Compress-Archive -Path $items -DestinationPath $bak -Force
Write-Host "已备份 -> $bak"

Write-Host "== 2/3 安装依赖（清华源） =="
& $py -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

Write-Host "== 3/3 PyInstaller 打包 =="
& $py -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name AutoFillFace `
    --icon AutoFillFace.ico `
    --add-data "assets\models;assets\models" `
    app\main.py

Write-Host "打包完成: $root\dist\AutoFillFace.exe"
