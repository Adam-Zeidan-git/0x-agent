# AutoClose (0x): POS End-of-Day and Stock-Management Agent

Single-file agent for store operations. It closes the trading day and works as a stock manager: it reads a stock report (PDF, CSV, Excel, JSON, text), finds what is low, expired, miscounted or short-delivered, and drafts the orders. Every figure comes from deterministic code, never from the model.

## Quickstart (any machine)

```bash
git clone <repo-url> 0x-agent && cd 0x-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
chmod +x *.sh
./demo.sh                              # full review of the Piazza 1140 sample case
```

## Web interface (no terminal needed after install)

```bash
0x-ui --open          # opens http://127.0.0.1:8080 in your browser
```

Pick a sample case or drop in your own stock file (and closing pack), choose a report, press **Run 0x**. It shows the report, a sortable issues table, the security notice if a document contained instructions aimed at an AI, and lets you copy or download the result. It runs the same code as the command line, only on your own computer, and never changes files (the owner report is a preview).

## Run it on your own case

Put your files in a folder. Names must contain `stock` and (optionally) `closing`:

```
samples/mycase/
  stock.pdf            # or .csv / .xlsx
  closing_pack.pdf     # optional
```

```bash
./run_case.sh samples/mycase
./run_case.sh samples/mycase --json
./run_case.sh samples/mycase --stock-tool tip_distribution
./run_case.sh samples/mycase --stock-tool usage_forecast
./run_case.sh samples/mycase --stock-tool owner_report --yes     # writes a draft file
```

Or call `0x` directly:

```bash
0x --stock-file path/to/stock.pdf --full --no-nim
0x --stock-file stock.pdf --closing-file pack.pdf --full --no-nim
0x --stock-file stock.pdf --full --out report.txt
0x --list-stock-tools
0x                                     # interactive chat
```

Chat example:

```
You: review stock samples/piazza1140/Piazza1140_stock_2026-11-14.pdf
You: closing pack samples/piazza1140/Piazza1140_closing_pack_2026-11-14.pdf
You: split the tips            -> authorize tip_distribution
You: when will we run out of napkins
```

Expected results for the sample are in `samples/piazza1140/ANSWER_KEY.md`. Run the tests with `python3 -m pytest tests -q`.

## Stock tools

| Tool | What it does |
|---|---|
| `check_stock_levels` | On hand and status for an item, category, or all |
| `low_stock_report` | Out, negative, at or below minimum |
| `reorder_suggestions` | Order quantity by supplier, with cost |
| `expiry_report` | Expired and expiring lots, projected waste |
| `count_variance` | Physical count vs system, shrinkage value |
| `receiving_check` | Ordered vs received |
| `stock_valuation` | Value at cost, ABC, overstock, below-cost prices |
| `stock_data_audit` | Duplicates, negatives, missing costs |
| `full_stock_review` | All of the above |
| `draft_purchase_orders` | Writes draft POs per supplier (needs `--yes`) |
| `apply_stock_adjustments` | Applies counts and write-offs (needs `--yes`) |

## Closing tools (need a closing pack PDF)

| Tool | What it does |
|---|---|
| `tip_distribution` | Splits tips: servers by sales, kitchen and bar/runners by hours (default 60/25/15) |
| `usage_forecast` | Sales x recipes + waste allowance: when each item runs out and when to order |
| `performance_trend` | Month comparison, projection with salaries, break-even covers |
| `closing_review` | Tips, forecast and trend together |
| `owner_report` | Writes the daily owner report to a file (draft, never emailed) |

## Security

Text inside a document is data, never an instruction. Anything that reads like an order to an AI is reported in a security notice and ignored. State-changing tools need explicit confirmation, honour freeze mode and `--dry-run`, and write only inside the data directory. Sensitive tools (tips, trend, owner report) need `authorize <tool>` in chat.

Limits: scanned (image-only) PDFs need OCR (`pip install -e ".[ocr]"` plus `tesseract` and `poppler`). The closing pack must be a PDF with ruled tables. The forecast is theoretical usage and cannot see theft or over-portioning beyond the allowance. With under 12 months of history it cannot separate season from trend.

## Configuration (optional)

Copy `.env.example` to `.env`. Without keys, 0x runs in deterministic mode.

| Variable | Purpose |
|---|---|
| `NIM_API_KEY`, `NIM_BASE_URL` | NVIDIA NIM reasoning |
| `AUTOCLOSE_NO_NIM` | `1` disables NIM |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Ollama for chat parsing (default `http://localhost:11434`, `llama3.2`) |
