# N-Boryl Pyridyl Anion Chemistry：首轮解析器评测

## 结论

首轮采用 PyMuPDF 作为主解析器，pdfplumber/pypdf 作为轻量备用和交叉检查工具。
Docling、GROBID 与 MinerU Adapter 已保留，但按当前阶段的成本控制要求不进行实跑。

| 解析器 | 状态 | 得分 | 门禁 | 结论 | 耗时 |
|---|---:|---:|---:|---:|---:|
| PyMuPDF | 成功 | 98.00 | 全部通过 | 采用 | 4.00 s |
| pdfplumber/pypdf | 成功 | 73.64 | 未通过 | 备用 | 4.47 s |
| Docling | 延后 | - | - | 重型可选 | - |
| GROBID | 跳过 | - | - | 需配置官方服务 | - |
| MinerU | 跳过 | - | - | 需显式云上传授权 | - |

## PyMuPDF

- 识别 13/13 页、5/5 个主体章节。
- 识别 Figure 1-11，页码和图注坐标全部正确。
- 标题、三位作者、DOI 和第 86 条参考文献均可识别。
- 10 个文字锚点命中 9 个；`pyridine/aldehyde coupling reaction` 因 PDF 换行被抽取为带空格的形式。
- 第 1、3、6、10、13 页视觉抽查正常。
- 局限：大量化学反应式是矢量内容，不能作为独立 raster image 直接导出；后续需要按 Figure 坐标做页面区域裁切。

## pdfplumber/pypdf

- 元数据和页数完整，适合做第二读取器和结果交叉核对。
- 五个章节均能找到，但默认文字流出现章节顺序问题。
- 只稳定关联 5/11 个 Figure 图注、页码和坐标，不满足证据模型门禁。
- 不作为主解析器，但可用于元数据验证和 PyMuPDF 失败时的文本降级。

## 架构决策

MVP 使用：

```text
PyMuPDF 主解析
  + pdfplumber/pypdf 元数据与文本交叉检查
  + Figure 坐标裁切（下一阶段）
```

重型和云端候选不会删除。新增扫描件、复杂表格或当前主解析器失败的论文后，再按需运行 Docling 或 MinerU，而不是作为每篇论文的默认依赖。

## 下一步

1. 把 PyMuPDF Adapter 接入上传工作流和 `PdfParser` 端口。
2. 将解析结果传给 Literature Analysis Skill，并保留页码和坐标证据。
3. 增加一篇带优化表、底物范围、机理实验和 SI 的原始研究论文作为第二黄金样本。

其中第 1 项及 Figure 图注识别、区域裁切、正文引用关联现已完成。本基准论文共
生成 11 个 Figure 资产，并建立 32 条正文引用关系。
