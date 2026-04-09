# PDF Exploration Findings

Target file: `/Users/shaoqing/workspace/PageIndex/《运行手册》（第1版）.pdf`

## What This PDF Is

This is not a typical narrative PDF or a simple report export. It is a large operational manual exported from Microsoft Word with strong manual-navigation conventions:

- 1340 physical pages
- 34.9 MB file size
- Embedded PDF outline/bookmarks are present
- Searchable text exists on almost every page
- The document uses section-local page numbering, not a single global page number stream

The raw metrics are in [`report.json`](/Users/shaoqing/workspace/PageIndex/spec/pdf_exploration/report.json).

## Key Special Properties

### 1. It already contains a rich built-in outline

The PDF has an embedded outline with 265 entries, including front matter and section titles such as:

- `0.7 - 有效页清单`
- `0.8 - 目录`
- `1.0 运行手册和记录管理`
- `2.4 运行限制或暂停运行的规定`

This matters because PageIndex is currently trying to reconstruct structure with LLM calls from extracted text, but this file already ships with a native navigation structure that is likely more reliable than the OCR/text-derived TOC path.

### 2. It contains two different front-matter navigation systems

The beginning is not a standard TOC-only pattern:

- Pages 11-16 are `有效页清单`
- Pages 17-28 are actual `目录`

The `有效页清单` is not a semantic TOC. It is closer to a validity / revision coverage list. Example patterns:

- `2.24/1-12`
- `6.9/1-8`
- `目录/I-XII`

This is the main reason the current PageIndex TOC path misfired: it detected those pages as TOC-like and tried to infer physical page offsets from values that are not simple page numbers.

### 3. Page numbering is section-local, not document-global

Most content pages do not show a global page number like `29`, `30`, `31`. They show labels like:

- `1.1-1`
- `1.1-2`
- `1.4-8`

Measured result:

- 1172 pages use this section-local label style
- 6 pages use Roman numerals in front matter

This is highly relevant because PageIndex's current TOC-to-physical-page offset logic assumes a more standard relationship between TOC page numbers and physical pages.

### 4. Front matter mixes Roman numerals and section labels

Examples:

- `I` through `VI` in the effective-page list
- `目录-I` through `目录-XII` in the table of contents
- body pages switch to `1.1-1`, `1.2-3`, etc.

This makes naive numeric page parsing brittle.

### 5. The file is searchable text, not primarily scanned images

This is important because it means the PDF is structurally unusual, but not OCR-hostile.

Measured result:

- searchable page ratio: `0.9955`
- median extracted text length per page: `611.5` chars

So the problem is not OCR failure. The problem is navigation semantics.

### 6. Layout is mixed but still regular enough to exploit

Measured result:

- dominant page size near A5 landscape-style dimensions: `419.5 x 595.3` and `419.6 x 595.3`
- 109 pages are landscape-like (`595.3 x 419.x` plus 2 oversized pages)
- 3 rotated pages

This is less important than the numbering issue, but it confirms the document is assembled from multiple layout templates rather than a single plain article format.

### 7. Some early pages are effectively blank in extracted text

Pages 1, 3, 4, 5 have zero extracted text. These are likely cover / approval / image-heavy pages. This is not unusual by itself, but it means the front matter is heterogeneous.

## Why It Differs From a "Typical" PDF

Compared with a normal report, paper, or handbook PDF, this file differs in several material ways:

- It has both a machine-readable outline and a human-readable TOC, and they are not the same thing.
- It has an `有效页清单` before the actual TOC, which looks TOC-like but is semantically different.
- It uses section-page labels like `6.9-3` instead of a single global page number stream.
- It mixes Roman numeral front matter, named TOC pages, and section-local numbering.
- It is very large, which amplifies failure modes when early structure inference goes wrong.

In practice, this means the current PageIndex logic is treating a regulated manual as if it were a standard long report. That assumption is weak.

## What This Means For PageIndex

### Current fit

Current fit is poor for the default TOC path.

The current logic:

- detects TOC pages from text shape
- tries to transform TOC entries into JSON
- tries to map TOC page values to physical pages through an offset

That logic is reasonable for ordinary TOCs. It is fragile for this file because:

- `有效页清单` contaminates TOC detection
- TOC "page" values are section-local ranges, not physical page numbers
- front matter numbering is mixed

### Stronger adaptation path

If we want to support this PDF class properly, the priority order should be:

1. Prefer embedded PDF outline/bookmarks when present.
2. Distinguish `有效页清单` from actual semantic TOC pages.
3. Treat values like `1-12`, `11-20`, `目录-I`, `I-VI` as section/range labels, not physical-page candidates.
4. Use repeated page header/footer patterns to infer section boundaries.
5. Only fall back to LLM TOC reconstruction when native outline and structural markers are absent.

## Recommendation

Do not treat this as a generic "TOC parsing bug" only.

Treat it as a separate PDF class:

- regulated manual / operational handbook
- embedded outline present
- section-local pagination
- effective-page list before TOC

For this class, an outline-first ingestion path is likely the right design. Adapting the current TOC offset heuristic alone will not be enough.

## Prototype Result

An outline-first prototype was built in [`outline_to_tree.py`](/Users/shaoqing/workspace/PageIndex/spec/pdf_exploration/outline_to_tree.py).

It successfully converts the embedded PDF outline into a tree with physical page ranges. Example result:

- `6.9 特殊机场和特殊航路` -> pages `353-360`
- `8.4.13.2 特殊机场验证试飞` -> pages `618-621`

This is already enough to support targeted retrieval against the manual without depending on the current TOC offset logic.

The `6.9` section was then manually checked from the extracted text. The domestic special-airport list currently includes:

- `迪庆/香格里拉`
- `丽江/三义`
- `腾冲/驼峰`
- `大连/周水子`
- `昭通`

Reference: [`special_airports_note.md`](/Users/shaoqing/workspace/PageIndex/spec/pdf_exploration/special_airports_note.md)
