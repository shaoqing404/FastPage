# Section 6.9 Extraction Note

Source section: `6.9 特殊机场和特殊航路`

Located from the embedded PDF outline:

- start page: `353`
- end page: `360`

Reference: [`outline_matches.json`](/Users/shaoqing/workspace/PageIndex/spec/pdf_exploration/outline_matches.json)

## Extracted special airports list

From `6.9.1.4 航空公司特殊机场清单`, the currently extracted domestic special airports are:

1. `迪庆/香格里拉`
2. `丽江/三义`
3. `腾冲/驼峰`
4. `大连/周水子`
5. `昭通`

The same section states:

- `境外：（暂无）`

## Why This Matters

This section is a good proof that an outline-first path is operationally useful:

- the chapter was located without relying on TOC reconstruction
- the located page range is tight enough for targeted extraction
- the answerable content sits in a small page window instead of requiring full-document indexing first

## Caveat

The `6.9.1.4` content is in a table-like layout, so plain text extraction preserves the airport names reliably but may fragment some right-column restrictions and descriptions across lines.
