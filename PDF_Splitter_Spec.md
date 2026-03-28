# AI 開發規格書
## PDF 圖文分離處理工具 PDF Text & Background Splitter

| 項目 | 說明 |
|------|------|
| 文件版本 | v1.0.0 |
| 建立日期 | 2026-03-27 |
| 開發語言 | Python 3.10+ |
| 目標平台 | Windows 10 / 11（x64） |
| 輸出格式 | 單一可執行檔 .exe（PyInstaller） |
| 輸入格式 | 標準未加密 PDF（課本，含繁中、英文、數字） |

---

## 1. 專案概述

本工具將一份普通未加密的 PDF（例如課本）自動拆分為兩份獨立輸出檔案：

- **文字層 PDF**（`text_layer.pdf`）：僅保留純文字，完全去除背景圖像與遮色片。
- **背景層 PDF**（`bg_layer.pdf`）：僅保留視覺背景圖案，完全去除文字與所有遮色片殘留區域。

核心技術難點：部分圖案使用**遮色片（Clipping Mask）**遮擋不需顯示的區域。移除遮色片後，原被遮蔽的像素會重新顯現，造成背景層出現雜訊。工具必須透過影像比對迴圈偵測並消除此類雜訊，直到相似度 ≥ 95%。

> ⚠️ **前提條件**：PDF 必須為未加密格式（無 DRM / 密碼保護）。內容可能同時含有繁體中文、英文字母及阿拉伯數字。

---

## 2. 功能需求

### 2.1 文字層提取（輸出 A）

從 PDF 物件樹中識別並保留所有文字物件（PDF text operators：`BT...ET`）。移除所有非文字物件，包含：

- XObject（圖像嵌入物件）
- Path 填色物件（背景幾何圖形）
- 所有 Clipping Path 與遮色片定義（`q...Q` 區塊中的 `W / W*` operator）

輸出結果：白底黑字或原色字體的純文字 PDF，每頁對應原始頁面。

> ℹ️ **文字識別範圍**：繁體中文（CJK Unicode）、英文字母（A-Z, a-z）、阿拉伯數字（0-9）、常見標點符號，均須正確保留不得遺漏。

---

### 2.2 背景層提取（輸出 B）

從 PDF 中識別並保留所有非文字的視覺圖形物件。移除所有文字物件（`BT...ET`）及其佔位空間，並清除遮色片殘留。

**關鍵流程**：先移除文字，以當前狀態作為「參考結果圖（Reference）」，再進行遮色片消除迴圈（見第 2.3 節）。

---

### 2.3 遮色片消除迴圈（核心演算法）

此步驟為工具的核心，處理移除遮色片後可能出現的雜訊像素。

**演算法流程（每頁獨立執行）：**

1. 將當前頁面渲染為高解析度影像（建議 300 DPI）作為 **Reference Image**。
2. 從 PDF 物件清單中取出下一個待檢查的元件（XObject、Path、Clipping Group）。
3. 暫時移除該元件後重新渲染，得到 **Candidate Image**。
4. 計算 SSIM（Structural Similarity Index）及像素差異熱圖。
5. 判斷：
   - 若 SSIM ≥ 0.95 → 確認移除，更新 Reference Image，繼續下一元件。
   - 若 SSIM < 0.95 → 該元件為必要遮色片殘留，還原元件，嘗試**部分遮蔽**（以白色矩形覆蓋差異區域）後重新比對。
   - 若部分遮蔽後仍 < 0.95 → 保留元件原樣，繼續下一元件。
6. 重複步驟 2–5 直至所有元件處理完畢。
7. 最終輸出當前 Reference Image 作為該頁背景層。

> 🎯 **收斂條件**：整頁所有元件處理完畢後，最終畫面與初始移除文字後的 Reference 相似度須 ≥ 95%，否則輸出警告並標記該頁供人工審查。

---

## 3. 技術規格

### 3.1 核心函式庫

| 函式庫 | 用途 | 版本要求 |
|--------|------|----------|
| `pymupdf (fitz)` | PDF 解析、物件操作、頁面渲染 | >= 1.23.0 |
| `Pillow (PIL)` | 影像處理、格式轉換 | >= 10.0.0 |
| `scikit-image` | SSIM 計算、影像比對 | >= 0.22.0 |
| `numpy` | 像素陣列運算、差異熱圖 | >= 1.26.0 |
| `tkinter` | GUI 介面（Python 內建） | 標準庫 |
| `PyInstaller` | 打包為單一 .exe | >= 6.0.0 |
| `opencv-python` | 影像前處理、遮色片區域偵測 | >= 4.9.0 |

---

### 3.2 PDF 解析策略

使用 PyMuPDF（fitz）存取 PDF 物件樹，分類每頁內的所有渲染指令：

| 物件類型 | PDF Operator | 文字層 | 背景層 |
|----------|-------------|--------|--------|
| 文字物件 | `BT ... ET` | ✅ 保留 | ❌ 移除 |
| 影像物件（XObject） | `Do` | ❌ 移除 | ✅ 保留 |
| 填色路徑（Background） | `f / F / f*` | ❌ 移除 | ✅ 保留 |
| 遮色片路徑 | `W / W* + clip` | ❌ 移除 | 🔄 迴圈處理 |
| 描邊路徑 | `S / s` | ❌ 移除 | ✅ 保留（通常） |

---

### 3.3 影像比對演算法

使用 **SSIM（Structural Similarity Index Measure）** 作為主要相似度指標，輔以像素均方差（MSE）做快速預篩。

```python
# 核心比對邏輯（偽代碼）
from skimage.metrics import structural_similarity as ssim
import cv2, numpy as np

def compare_images(ref: np.ndarray, candidate: np.ndarray) -> tuple[float, np.ndarray]:
    gray_ref  = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    gray_cand = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
    score, diff_map = ssim(gray_ref, gray_cand, full=True)
    return score, diff_map  # score ∈ [0.0, 1.0]
```

差異熱圖（`diff_map`）須在 GUI 中即時顯示，協助使用者理解當前比對狀態。

---

## 4. GUI 介面規格

### 4.1 框架選擇

使用 Python 內建 **Tkinter** 框架，搭配 `ttk` 主題。  
選用理由：無需額外依賴、易於 PyInstaller 打包、Windows 原生外觀。

---

### 4.2 主視窗佈局

| 區域 | 位置 | 說明 |
|------|------|------|
| 工具列 | 頂部全寬 | 開啟 PDF、開始處理、停止、設定 |
| 左側面板 | 左側 40% | 原始 PDF 預覽（每頁縮圖列表） |
| 中央主區 | 中央 60% | 即時比對畫面（Reference / Candidate / Diff） |
| 底部狀態列 | 底部全寬 | 處理進度條、當前步驟說明、SSIM 數值顯示 |
| 右側日誌 | 右側抽屜式 | 逐步操作記錄（可收合） |

---

### 4.3 即時比對畫面（核心 UI）

中央主區分為三格水平排列，每完成一次元件比對後即時更新：

- **左格「參考圖 Reference」**：當前目標狀態的渲染圖。
- **中格「候選圖 Candidate」**：移除某元件後的渲染圖。
- **右格「差異熱圖 Diff Map」**：紅色高亮顯示兩圖差異區域；差異越大顏色越深。

**SSIM 數值**顯示於每格下方：≥ 0.95 呈綠色，低於門檻呈紅色警示。

---

### 4.4 設定面板

| 參數 | 預設值 | 說明 |
|------|--------|------|
| 渲染 DPI | 300 | 頁面渲染解析度，越高越精確但速度越慢 |
| SSIM 門檻 | 0.95 | 相似度達到此值視為元件可安全移除 |
| 最大迭代次數 | 200 | 每頁元件比對的上限次數 |
| 輸出目錄 | 同輸入資料夾 | 指定輸出 PDF 的儲存路徑 |
| 多頁並行 | 關閉 | 開啟後使用多執行緒同時處理多頁（記憶體需求較高） |

---

## 5. 完整處理流程

### 5.1 主要流程

1. 使用者選擇 PDF 檔案，工具讀取並顯示頁面清單。
2. 使用者確認參數設定後，點擊「開始處理」。
3. 工具對每一頁依序執行：
   1. 解析該頁 PDF 物件，分類文字 / 圖形 / 遮色片。
   2. 生成文字層：移除所有非文字物件，輸出純文字頁。
   3. 生成背景層：移除文字，以當前狀態為 Reference，進入遮色片消除迴圈。
   4. 遮色片消除迴圈逐一比對每個元件（見 2.3 節），更新即時畫面。
   5. 迴圈完成後，將最終 Reference 影像嵌入背景層 PDF。
4. 全部頁面處理完畢，輸出兩份 PDF 並顯示完成摘要。

---

### 5.2 錯誤處理

| 情境 | 處理方式 |
|------|----------|
| PDF 有加密或密碼保護 | 提示「不支援加密 PDF」，終止處理 |
| 某頁 SSIM 最終 < 0.95 | 輸出警告，該頁以黃色標記供人工審查，不中斷整體流程 |
| 元件數量超過最大迭代次數 | 停止該頁迴圈，記錄未處理元件數量至日誌 |
| 記憶體不足（大型 PDF） | 自動降低 DPI 至 150 後重試，並通知使用者 |
| 輸出路徑無寫入權限 | 彈出對話框請使用者重新選擇路徑 |

---

## 6. 專案結構

```
pdf_splitter/
├── main.py                 # 程式進入點，初始化 GUI
├── gui/
│   ├── main_window.py      # 主視窗佈局與事件綁定
│   ├── preview_panel.py    # 左側 PDF 縮圖預覽
│   ├── compare_panel.py    # 中央三格比對畫面
│   └── settings_dialog.py  # 設定對話框
├── engine/
│   ├── pdf_parser.py       # PDF 物件解析與分類
│   ├── layer_extractor.py  # 文字層 / 背景層提取邏輯
│   ├── mask_resolver.py    # 遮色片消除迴圈
│   └── image_comparator.py # SSIM 比對與熱圖生成
├── utils/
│   ├── logger.py           # 日誌記錄工具
│   └── file_helper.py      # 檔案路徑工具函數
├── assets/
│   └── icon.ico            # 應用程式圖示
├── requirements.txt        # 依賴套件清單
└── build.spec              # PyInstaller 打包設定
```

---

## 7. 打包規格（PyInstaller）

### 7.1 打包指令

```bash
# 安裝依賴
pip install -r requirements.txt

# 打包為單一 exe（含所有依賴）
pyinstaller build.spec
```

```python
# build.spec 關鍵設定
a = Analysis(['main.py'], ...)
exe = EXE(
    a.scripts,
    name='PDF_Splitter',
    icon='assets/icon.ico',
    onefile=True,      # 單一 exe
    windowed=True,     # 不顯示 cmd 視窗
    ...
)
```

---

### 7.2 打包注意事項

- `pymupdf` 含有 C 擴充，**必須在 Windows 環境下打包**（不可在 Linux/Mac 交叉編譯）。
- `opencv-python` 需加入 `--collect-submodules cv2` 避免漏包。
- `tkinter` 在部分 Python 發行版可能需要額外指定 `--hidden-import tkinter`。
- 最終 `.exe` 檔案預估大小：**150–250 MB**（含 pymupdf 和 cv2 二進位）。

> 💡 **建議**：使用虛擬環境（venv）打包，避免非必要套件混入，可有效縮小 exe 體積。

---

## 8. 效能需求與限制

| 指標 | 目標值 | 備註 |
|------|--------|------|
| 單頁處理時間（300 DPI） | < 60 秒 | 含所有元件比對迭代 |
| 記憶體峰值 | < 2 GB | 對 A4 全彩頁面 |
| 支援最大頁數 | 無硬性上限 | 建議分批處理 300 頁以上的檔案 |
| SSIM 計算速度 | < 0.5 秒 / 次 | A4 300 DPI 單頁 |
| GUI 更新頻率 | 每次迭代後即時更新 | 不得造成介面凍結（使用 Thread） |

---

## 9. 驗收條件

開發完成後，須滿足以下**所有條件**方視為完成：

1. 文字層 PDF 中不含任何圖像或背景元素，文字位置與原 PDF 完全對應。
2. 背景層 PDF 中不含任何可識別文字，背景圖案視覺上與原始 PDF 一致。
3. 遮色片移除後，背景層不出現額外的雜訊圖形（各頁 SSIM ≥ 0.95）。
4. GUI 在處理過程中即時顯示三格比對畫面（Reference / Candidate / Diff），畫面不凍結。
5. 底部狀態列顯示正確的處理進度百分比與當前 SSIM 數值。
6. 可在 Windows 10 / 11 上以單一 `.exe` 執行，無需安裝任何 Python 環境。
7. 對加密 PDF 顯示明確錯誤提示，不崩潰。
8. 含有繁體中文、英文字母、數字的課本 PDF 均能正確分離，文字不遺漏。

---

## 10. 建議開發順序

| 階段 | 任務 | 重點 |
|------|------|------|
| Phase 1 | 核心引擎開發 | 實作 `pdf_parser.py`、`layer_extractor.py`，以命令列驗證文字 / 背景拆分正確性 |
| Phase 2 | 遮色片消除迴圈 | 實作 `mask_resolver.py` 與 `image_comparator.py`，確認 SSIM 迴圈收斂 |
| Phase 3 | GUI 介面開發 | 實作 Tkinter 主視窗、三格比對畫面、進度條，確保多執行緒不凍結 |
| Phase 4 | 整合測試 | 以多份課本 PDF 測試（純文字、圖文混排、大量遮色片頁面） |
| Phase 5 | PyInstaller 打包 | 在 Windows 環境打包，測試 exe 可獨立執行 |

---

## 附錄 A：SSIM 說明

SSIM（Structural Similarity Index Measure）是衡量兩張影像結構相似程度的指標，範圍 0.0～1.0。與單純的像素差異（MSE）不同，SSIM 考量**亮度、對比度與結構**三個維度，更接近人眼對圖像品質的感知。

| SSIM 範圍 | 解讀 |
|-----------|------|
| 0.95 ～ 1.00 | 視覺上幾乎完全相同，元件可安全移除 |
| 0.85 ～ 0.94 | 輕微差異，需進一步判斷是否為遮色片殘留 |
| < 0.85 | 明顯差異，元件為必要視覺元素，應保留 |

---

## 附錄 B：名詞對照表

| 中文名詞 | 英文 / 技術名稱 | 說明 |
|----------|----------------|------|
| 遮色片 | Clipping Mask / Clipping Path | PDF 中用於遮蔽圖形特定區域的路徑定義 |
| 文字物件 | Text Object (BT...ET) | PDF 內容流中的文字渲染區塊 |
| 影像物件 | XObject (Image) | PDF 中嵌入的點陣圖影像參照 |
| 結構相似度 | SSIM | 用於量化兩圖視覺差異的數值指標 |
| 差異熱圖 | Diff Map / Heatmap | 以顏色深淺呈現兩圖像素差異位置的視覺化圖 |
| 打包 | PyInstaller Packaging | 將 Python 程式與依賴封裝為單一 exe 的流程 |
