from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.table import WD_TABLE_ALIGNMENT

doc = Document()

section = doc.sections[0]
section.page_width   = Inches(8.27)
section.page_height  = Inches(11.69)
section.left_margin  = Cm(2.2)
section.right_margin = Cm(2.2)
section.top_margin   = Cm(2.5)
section.bottom_margin= Cm(2.5)

ORANGE  = RGBColor(0xF5, 0x7C, 0x00)
NAVY    = RGBColor(0x12, 0x14, 0x2E)
NAVY2   = RGBColor(0x1E, 0x20, 0x3E)
SLATE   = RGBColor(0x44, 0x44, 0x66)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
TEXT    = RGBColor(0x22, 0x22, 0x33)
ROW_ALT = RGBColor(0xF5, 0xF5, 0xFA)
ROW_WHT = RGBColor(0xFF, 0xFF, 0xFF)
TIP_BG  = RGBColor(0xFF, 0xF3, 0xE0)
NOTE_BG = RGBColor(0xEE, 0xF2, 0xFF)
AMBER_C = RGBColor(0xC0, 0x6A, 0x00)
BLUE_C  = RGBColor(0x33, 0x44, 0x99)

def hx(rgb): return '{:02X}{:02X}{:02X}'.format(rgb[0], rgb[1], rgb[2])

def shade_para(para, rgb):
    pPr = para._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), hx(rgb))
    pPr.append(shd)

def shade_cell(cell, rgb):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), hx(rgb))
    tcPr.append(shd)

def cell_margins(cell, top=90, bottom=90, left=130, right=130):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for s,v in [('top',top),('bottom',bottom),('left',left),('right',right)]:
        el = OxmlElement(f'w:{s}'); el.set(qn('w:w'), str(v)); el.set(qn('w:type'), 'dxa'); tcMar.append(el)
    tcPr.append(tcMar)

def tbl_borders(t, color='DDDDEE', sz='4'):
    tbl = t._tbl
    tblPr = tbl.find(qn('w:tblPr'))
    if tblPr is None: tblPr = OxmlElement('w:tblPr'); tbl.insert(0, tblPr)
    tb = OxmlElement('w:tblBorders')
    for s in ('top','left','bottom','right','insideH','insideV'):
        el = OxmlElement(f'w:{s}'); el.set(qn('w:val'),'single'); el.set(qn('w:sz'),sz)
        el.set(qn('w:space'),'0'); el.set(qn('w:color'),color); tb.append(el)
    tblPr.append(tb)

def p_border_bottom(para, color='F57C00', sz='6'):
    pPr = para._p.get_or_add_pPr()
    pb = OxmlElement('w:pBdr'); b = OxmlElement('w:bottom')
    b.set(qn('w:val'),'single'); b.set(qn('w:sz'),sz); b.set(qn('w:space'),'1'); b.set(qn('w:color'),color)
    pb.append(b); pPr.append(pb)

def p_border_left(para, color='F57C00', sz='24'):
    pPr = para._p.get_or_add_pPr()
    pb = OxmlElement('w:pBdr'); b = OxmlElement('w:left')
    b.set(qn('w:val'),'single'); b.set(qn('w:sz'),sz); b.set(qn('w:space'),'8'); b.set(qn('w:color'),color)
    pb.append(b); pPr.append(pb)

def h1(doc, text):
    p = doc.add_paragraph(); shade_para(p, NAVY)
    p.paragraph_format.space_before = Pt(24); p.paragraph_format.space_after = Pt(8)
    r = p.add_run(f'   {text}')
    r.bold=True; r.font.size=Pt(15); r.font.color.rgb=ORANGE; r.font.name='Calibri'

def h2(doc, text):
    p = doc.add_paragraph(); p_border_bottom(p)
    p.paragraph_format.space_before=Pt(16); p.paragraph_format.space_after=Pt(5)
    r = p.add_run(text); r.bold=True; r.font.size=Pt(12); r.font.color.rgb=NAVY; r.font.name='Calibri'

def body(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before=Pt(2); p.paragraph_format.space_after=Pt(6)
    r = p.add_run(text); r.font.size=Pt(10); r.font.color.rgb=TEXT; r.font.name='Calibri'

def bi(doc, bold_part, rest):
    p = doc.add_paragraph()
    p.paragraph_format.space_before=Pt(2); p.paragraph_format.space_after=Pt(5)
    r1=p.add_run(bold_part); r1.bold=True; r1.font.size=Pt(10); r1.font.color.rgb=NAVY; r1.font.name='Calibri'
    r2=p.add_run(rest); r2.font.size=Pt(10); r2.font.color.rgb=TEXT; r2.font.name='Calibri'

def bullet(doc, text, label=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_before=Pt(1); p.paragraph_format.space_after=Pt(2)
    p.paragraph_format.left_indent=Cm(0.6)
    r0=p.add_run('\u2022  '); r0.font.color.rgb=ORANGE; r0.font.size=Pt(10); r0.font.name='Calibri'
    if label:
        r1=p.add_run(label+'  '); r1.bold=True; r1.font.size=Pt(10); r1.font.color.rgb=NAVY; r1.font.name='Calibri'
    r2=p.add_run(text); r2.font.size=Pt(10); r2.font.color.rgb=TEXT; r2.font.name='Calibri'

def tip(doc, text):
    p = doc.add_paragraph(); shade_para(p, TIP_BG); p_border_left(p, color='F57C00')
    p.paragraph_format.space_before=Pt(6); p.paragraph_format.space_after=Pt(8)
    p.paragraph_format.left_indent=Cm(0.4)
    r1=p.add_run('\U0001f4a1  Tip:  '); r1.bold=True; r1.font.size=Pt(9.5); r1.font.color.rgb=AMBER_C; r1.font.name='Calibri'
    r2=p.add_run(text); r2.font.size=Pt(9.5); r2.font.color.rgb=TEXT; r2.font.name='Calibri'; r2.italic=True

def note(doc, text):
    p = doc.add_paragraph(); shade_para(p, NOTE_BG); p_border_left(p, color='5560AA')
    p.paragraph_format.space_before=Pt(6); p.paragraph_format.space_after=Pt(8)
    p.paragraph_format.left_indent=Cm(0.4)
    r1=p.add_run('\u2139\ufe0f  Note:  '); r1.bold=True; r1.font.size=Pt(9.5); r1.font.color.rgb=BLUE_C; r1.font.name='Calibri'
    r2=p.add_run(text); r2.font.size=Pt(9.5); r2.font.color.rgb=TEXT; r2.font.name='Calibri'; r2.italic=True

def tbl(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1+len(rows), cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.LEFT; tbl_borders(t)
    hr = t.rows[0]
    for i,h in enumerate(headers):
        c=hr.cells[i]; shade_cell(c, NAVY2); cell_margins(c,100,100)
        p=c.paragraphs[0]; r=p.add_run(h)
        r.bold=True; r.font.size=Pt(9.5); r.font.color.rgb=ORANGE; r.font.name='Calibri'
        p.paragraph_format.space_before=Pt(0); p.paragraph_format.space_after=Pt(0)
    for ri, rd in enumerate(rows):
        bg = ROW_ALT if ri%2==0 else ROW_WHT
        row = t.rows[ri+1]
        for ci, val in enumerate(rd):
            c=row.cells[ci]; shade_cell(c,bg); cell_margins(c)
            p=c.paragraphs[0]; r=p.add_run(str(val))
            r.font.size=Pt(9.5); r.font.color.rgb=TEXT; r.font.name='Calibri'
            p.paragraph_format.space_before=Pt(0); p.paragraph_format.space_after=Pt(0)
    if widths:
        for row in t.rows:
            for ci,w in enumerate(widths): row.cells[ci].width=Cm(w)
    doc.add_paragraph().paragraph_format.space_after=Pt(4)

def numbered(doc, n, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before=Pt(2); p.paragraph_format.space_after=Pt(4)
    p.paragraph_format.left_indent=Cm(0.6)
    r1=p.add_run(f'{n}.  '); r1.bold=True; r1.font.size=Pt(10); r1.font.color.rgb=ORANGE; r1.font.name='Calibri'
    r2=p.add_run(text); r2.font.size=Pt(10); r2.font.color.rgb=TEXT; r2.font.name='Calibri'

# ── COVER ─────────────────────────────────────────────────────────────────────
p = doc.add_paragraph(); shade_para(p, NAVY)
p.paragraph_format.space_before=Pt(80); p.paragraph_format.space_after=Pt(0)
r=p.add_run('   EGG BASKET'); r.bold=True; r.font.size=Pt(40); r.font.color.rgb=ORANGE; r.font.name='Calibri'

p = doc.add_paragraph(); shade_para(p, NAVY); p.paragraph_format.space_after=Pt(0)
r=p.add_run('   UK Stock Screener'); r.font.size=Pt(20); r.font.color.rgb=WHITE; r.font.name='Calibri'

p = doc.add_paragraph(); shade_para(p, NAVY); p.paragraph_format.space_after=Pt(0)
r=p.add_run('   User Guide'); r.italic=True; r.font.size=Pt(14); r.font.color.rgb=RGBColor(0xAA,0xAA,0xCC); r.font.name='Calibri'

p = doc.add_paragraph(); shade_para(p, NAVY); p.paragraph_format.space_after=Pt(100); p.add_run('')
doc.add_page_break()

# ── WHAT IS EGG BASKET ────────────────────────────────────────────────────────
h1(doc, '  What is Egg Basket?')
body(doc, 'Egg Basket is a web-based research tool for finding, evaluating, and monitoring UK-listed stocks. Rather than wading through individual company reports, it pulls together the numbers that matter most \u2014 financial health, valuation, growth, and market momentum \u2014 into a single screen, so you can compare hundreds of companies at a glance and drill into the ones that interest you.')
body(doc, 'The tool has two main jobs:')
bullet(doc, 'Screening \u2014 filtering the market down from hundreds of companies to the handful that match your criteria.', None)
bullet(doc, 'Analysis \u2014 once you have found a candidate, giving you the financial detail to decide whether it deserves further research.', None)
body(doc, 'It also includes market-wide tools \u2014 a Fear & Greed index, a sector rotation model, and macro indicators \u2014 to help you understand the broader environment your stocks are operating in.')
tip(doc, 'Start with the Screener to find candidates, then click through to a Company Detail page to understand whether the numbers justify further research.')

# ── GETTING AROUND ────────────────────────────────────────────────────────────
h1(doc, '  Getting Around')
h2(doc, 'The Navigation Bar')
body(doc, 'The bar at the top of the screen is always visible. From left to right:')
bi(doc, 'Egg Basket logo  ', '\u2014  returns you to the main screener from anywhere in the app.')
bi(doc, 'Screener  ', '\u2014  the main stock list. Most sessions start here.')
bi(doc, 'Sector Analysis  ', '\u2014  dropdown for Rotation, Breadth, and Signal Log pages.')
bi(doc, 'Markets  ', '\u2014  dropdown for Fear & Greed and Cross-Asset (currencies, commodities, gilt yields).')
bi(doc, '\u21bb Market  ', '\u2014  refreshes all live data: benchmarks, VIX, sector prices, Fear & Greed. Use this at the start of each session.')
bi(doc, '\u21bb Stock Prices  ', '\u2014  updates the price history database for all stocks. Run once a day to keep charts and momentum scores current. A toast confirms how many rows were added.')
bi(doc, 'Search box  ', '\u2014  type any ticker (e.g. AZN) or company name. On the screener it scrolls to and highlights that row; elsewhere it opens the company page directly.')

h2(doc, 'The Left Sidebar')
body(doc, 'The sidebar gives you a live market snapshot at all times. It refreshes when you press \u21bb Market and can be collapsed with the panel icon in the top-left of the navbar.')
bullet(doc, 'The three FTSE benchmarks show how the broad market is moving today \u2014 a quick orientation before anything else.', None)
bullet(doc, 'VIX is the US equity volatility index and a widely-watched measure of investor anxiety. Below 20 is calm; above 30 is elevated; above 40 is panic territory.', None)
bullet(doc, 'UK Fear & Greed shows the app\u2019s composite sentiment score, its direction of travel, and which business cycle phase it is pointing to. The full explanation is in the Markets section.', None)
bullet(doc, 'ICB Sectors shows today\u2019s percentage move for each major industry group \u2014 useful for spotting what is leading or lagging on any given day.', None)
bullet(doc, 'Model Signal shows the current cycle phase, the percentage of FTSE 100 stocks in healthy uptrends, and which sector has the strongest relative momentum right now.', None)

# ── THE SCREENER ──────────────────────────────────────────────────────────────
doc.add_page_break()
h1(doc, '  The Screener')
body(doc, 'The screener is a filterable table of every UK-listed company in the database. Think of it as a search engine for stocks: set your criteria and it returns the companies that match. The table updates live as you adjust the filters \u2014 there is no button to press.')

h2(doc, 'Standard Filters')
bullet(doc, 'narrows results to a specific industry group (e.g. Technology, Health Care, Financials).', label='Sector')
bullet(doc, 'limits results to companies in the FTSE 100, 250, 350, SmallCap, or the full All-Share.', label='FTSE Index')
bullet(doc, 'sets a minimum company size in billions of pounds. Use this to filter out very small companies that may be illiquid or thinly researched.', label='Market Cap')

h2(doc, 'Advanced Filters')
body(doc, 'Click Advanced \u25bc to reveal seven more filters. The button turns orange when any are active. The company count above the table (e.g. \u201c47 / 312 companies\u201d) updates in real time.')
bullet(doc, 'a measure of recent price strength relative to peers. Stocks with high momentum have been trending upward steadily over the past year. The evidence base for momentum strategies is well-established \u2014 stocks that have been rising tend to continue outperforming in the near term.', label='Momentum')
bullet(doc, 'a summary of business quality: strong returns on capital, healthy margins, and consistent free cash flow. A high Quality score suggests a company with a durable competitive advantage.', label='Quality')
bullet(doc, 'the Piotroski F-Score \u2014 a nine-point checklist of whether fundamentals are improving. It does not measure cheapness; it measures direction. A high score means things are getting better across profitability, leverage, and efficiency.', label='Value')
bullet(doc, 'a measure of financial fragility, blending balance-sheet stress with price volatility. Lower is better. Use this to exclude companies that look stretched or unpredictable.', label='Risk')
tip(doc, 'A useful starting screen: Quality \u22658, Value \u22656, Risk \u22645. This finds improving, quality businesses with manageable risk \u2014 typically 20\u201350 names from the full All-Share.')

h2(doc, 'Reading the Results Table')
body(doc, 'Each row is one company. Colour coding gives you an instant signal on the most important metrics:')
tbl(doc,
    ['Column', 'What it measures', 'Colour signal'],
    [
        ['P/E',         'Price relative to earnings \u2014 a valuation measure',                    'Green <15 (cheap); red >40 (expensive)'],
        ['ROE',         'Profit generated per pound of shareholder equity',                         'Green if positive; red if negative'],
        ['Rev Growth',  'Year-on-year revenue growth',                                              'Green if growing; red if shrinking'],
        ['D/E',         'Debt-to-equity \u2014 how leveraged the balance sheet is',                'Red if above 2'],
        ['Momentum',    'Percentile rank of 12-1M price return vs the screened universe',          'Green \u22657; amber \u22654; red <4'],
        ['Quality',     'Composite: returns on capital, margins, free cash flow',                  'Green \u22657; amber \u22654; red <4'],
        ['Value',       'Piotroski F-Score (0\u20139) \u2014 are fundamentals improving?',          'Green \u22657; amber \u22654; red <4'],
        ['Risk',        'Blend of Altman Z-Score and price volatility (1\u201310)',                'Green \u22643; amber \u22646; red >6'],
    ],
    widths=[2.2, 5.8, 7.5]
)
body(doc, 'Click any row to open the full Company Detail page for that stock.')

# ── COMPANY DETAIL ────────────────────────────────────────────────────────────
doc.add_page_break()
h1(doc, '  Company Detail')
body(doc, 'Clicking a company opens its detail page. The header shows the name, ticker, sector, FTSE index membership, market cap, enterprise value, and a short description where available. Six tabs let you investigate different aspects of the business. Use \u2190 Back to Screener to return to your filtered list without losing your settings.')

h2(doc, 'Chart \u2014 What is the price doing?')
body(doc, 'The chart shows the daily closing price as an area chart. Use the time range buttons \u2014 1M through to 5Y \u2014 to zoom in and out. A one-month view reveals recent momentum; a three-year view shows whether the current price is near historical highs or recovering from a trough.')
body(doc, 'Two moving average overlays are available:')
bullet(doc, 'a short-term trend line (amber dashed). When price is above MA20 and MA20 is rising, the stock is in a short-term uptrend.', label='MA20 (20-day)')
bullet(doc, 'a medium-term trend line (purple solid). Price above both moving averages with MA50 rising signals a positive trend. Price below both signals decline. A cross of the MA50 often marks a change in direction.', label='MA50 (50-day)')
tip(doc, 'Check the chart before acting on any screener result. A strong Quality score in a stock that has already run 50% in three months may not represent the best entry point.')

h2(doc, 'Overview \u2014 Is this a good business?')
body(doc, 'The Overview tab is your first stop for a business quality check. Twelve colour-coded metric cards give you the key numbers at a glance \u2014 revenue, profit, cash flow, valuation ratios, and capital efficiency \u2014 without having to open a company report.')
body(doc, 'The bar chart at the bottom shows revenue and net income side by side over recent years. Growing bars indicate an expanding business. A large gap between revenue and net income bars signals thin margins.')

h2(doc, 'Financials \u2014 How has the business performed over time?')
body(doc, 'This tab is for trend analysis. Three questions to focus on:')
bullet(doc, 'Is revenue growing consistently, or is it lumpy and stagnant?', None)
bullet(doc, 'Is free cash flow (FCF) positive and growing? FCF is the cash the business actually generates after funding its operations and capital investment. Unlike reported profit, it cannot easily be manufactured through accounting choices \u2014 it is the closest thing to a company\u2019s real earning power.', None)
bullet(doc, 'Does the quarterly revenue chart show acceleration or deceleration? This tells you whether the most recent trading is better or worse than the annual average suggests.', None)
body(doc, 'The five-year income statement table at the bottom is a condensed profit and loss account. Negative numbers appear in red. Watch for years where net income diverges sharply from EBITDA \u2014 this can signal high interest costs, large depreciation charges, or one-off items distorting the picture.')

h2(doc, 'Valuation \u2014 What are you paying?')
body(doc, 'The Valuation tab answers whether the stock is cheap or expensive relative to its fundamentals. The eight valuation cards cover the ratios most commonly used by professional investors:')
bullet(doc, 'the most familiar valuation measure. A low P/E can mean cheapness or a troubled business; a high P/E implies the market expects strong future growth.', label='P/E')
bullet(doc, 'compares market price to the accounting value of assets. Most useful for banks, insurers, and capital-intensive businesses.', label='P/B')
bullet(doc, 'useful when a company has little or no profit, as it values the revenue stream directly.', label='P/S')
bullet(doc, 'enterprise value relative to operating earnings, independent of capital structure. One of the most widely used ratios for comparing companies with different levels of debt.', label='EV/EBITDA')
bullet(doc, 'the most reliable indicators of competitive advantage. A company sustaining high, stable returns on capital over many years typically has a genuine edge over its competitors.', label='ROE / ROIC / ROCE')
body(doc, 'The Return on Capital chart plots ROE, ROIC, and ROA together over time. Consistently high and stable returns are a strong quality signal. Erratic or structurally declining returns suggest competitive pressure or management issues.')

h2(doc, 'Health \u2014 Could this company get into trouble?')
body(doc, 'This tab focuses on financial risk. The large Risk Score at the top is the app\u2019s composite fragility rating:')
tbl(doc,
    ['Score', 'What it means', 'Suggested action'],
    [
        ['1\u20133  (green)', 'Solid balance sheet, low volatility',                   'Proceed with normal analysis'],
        ['4\u20136  (amber)', 'Some leverage or volatility worth noting',               'Review the balance sheet metrics in detail'],
        ['7\u201310 (red)',   'Elevated risk: high debt or distress signals present',   'Check Altman Z-Score and Debt/Equity trend before proceeding'],
    ],
    widths=[2.4, 6.0, 7.1]
)
body(doc, 'The Altman Z-Score is a well-tested academic model that predicts financial distress from five accounting ratios. A score above 3.0 is healthy. Below 1.8 is the distress zone \u2014 not necessarily heading for insolvency, but worth close scrutiny. The 1.8\u20133.0 range is the grey zone.')
body(doc, 'The Debt/Equity chart over time tells you whether leverage is rising or falling. Steadily increasing debt not matched by rising profitability is a warning sign. The Current Ratio chart shows whether the company can meet its short-term obligations \u2014 a ratio persistently below 1.0 is concerning.')
note(doc, 'A high Risk Score does not automatically make a stock uninvestable. Capital-heavy sectors like utilities and real estate routinely carry more debt than industrials. Always read risk in its sector context.')

h2(doc, 'Growth \u2014 Is the business expanding?')
body(doc, 'The Growth tab shows how quickly the company is growing its revenues, earnings, and cash flows. All figures are colour-coded: green for growth, red for contraction.')
body(doc, 'The 10-year CAGR (Compound Annual Growth Rate) figures are particularly valuable \u2014 they smooth out any one exceptional or disappointing year and show the underlying pace of the business across a full economic cycle. A company compounding revenue at 10% per year for a decade is a fundamentally different proposition to one growing at 2%.')
body(doc, 'The Profit Margins chart at the bottom plots gross, operating, and net margins together over time. Stable or widening margins suggest pricing power. Margins compressing while revenue grows can indicate rising input costs or intensifying competition \u2014 a business becoming less profitable even as it gets bigger.')

# ── SECTOR ANALYSIS ───────────────────────────────────────────────────────────
doc.add_page_break()
h1(doc, '  Sector Analysis')
body(doc, 'The Sector Analysis section helps you understand which parts of the UK market are in favour and which are not. It is built on the observation that at any point in the economic cycle, certain sectors tend to lead and others tend to lag. Getting sector positioning broadly right can matter as much as picking the right individual stocks.')

h2(doc, 'Sector Rotation \u2014 The Heatmap')
body(doc, 'The heatmap shows all eleven tracked ICB sectors ranked by their relative strength (RS) score \u2014 a measure of each sector\u2019s recent price performance compared to the FTSE All-Share. A score above 1.0 means outperforming; below 1.0 means lagging. The top four sectors are highlighted green; the bottom four red.')
body(doc, 'Use this to tilt your screener results towards sectors with momentum behind them. A fundamentally attractive stock in a sector showing a red signal faces a headwind that a similar stock in a green sector does not.')

h2(doc, 'The Business Cycle Wheel')
body(doc, 'Markets tend to rotate through a repeating four-phase cycle, and sector leadership shifts predictably as conditions change. The cycle wheel shows the app\u2019s current reading:')
tbl(doc,
    ['Phase', 'Economic backdrop', 'Sectors that historically lead'],
    [
        ['Recovery',    'Economy turning up from a trough; credit loosening; consumer confidence returning',     'Consumer Discretionary, Financials, Real Estate'],
        ['Expansion',   'Broad growth; corporate earnings rising; investment spending picking up',               'Industrials, Technology, Materials'],
        ['Slowdown',    'Growth peaking; inflation often elevated; central banks tightening',                    'Energy, Health Care, Consumer Staples'],
        ['Contraction', 'Recession or near-recession; earnings falling; risk aversion high',                    'Utilities, Health Care, Consumer Staples'],
    ],
    widths=[2.5, 6.0, 7.0]
)
body(doc, 'Below the wheel, two signals inform the current phase: one based on the Fear & Greed index and one based on which sectors are leading by RS score. When both agree, the reading is more reliable. When they diverge, treat the current phase with more caution.')
body(doc, 'The Favour and Avoid lists show which sectors are recommended for the current phase. Use these to inform the Sector filter in the screener. Clicking Accept on a suggested phase manually sets the cycle model and logs the change in the Signal Log.')
tip(doc, 'The cycle model is a guide, not a rule. Always cross-check with actual RS scores and breadth data before making sector allocation decisions.')

h2(doc, 'The RS Ranking Table')
body(doc, 'The table beneath the wheel gives you the full sector picture in one view:')
bullet(doc, 'the sector\u2019s price strength relative to the market. Above 1.0 = outperforming.', label='RS Score')
bullet(doc, 'whether the RS score is rising (\u2191) or falling (\u2193). A sector with RS above 1.0 but a falling trend may be about to lose its leadership position.', label='Trend')
bullet(doc, 'the percentage of stocks within the sector trading above their 50-day moving average. High breadth means many stocks are participating in the sector move, not just one or two large caps skewing the index.', label='Breadth')
bullet(doc, 'BUY when RS is above 1.05 and rising; AVOID when RS is below 0.95 and falling; NEUTRAL otherwise.', label='Signal')

h2(doc, 'Market Breadth')
body(doc, 'Breadth measures the health of a market advance. An index rising while most individual stocks within it are falling is a warning sign \u2014 the move is being driven by a handful of large names and is therefore fragile. The three summary cards give you a quick read on participation:')
bullet(doc, 'the percentage of a FTSE 100 basket trading above its 50-day moving average. Above 60% is broadly healthy (bullish breadth); below 40% means most stocks are in downtrends (bearish breadth). This is the single most important number on this page.', label='% Above 50-Day MA')
bullet(doc, 'how many basket stocks are at a new 52-week high vs a new 52-week low. More new highs than lows is consistent with a healthy market; the reverse signals deterioration under the surface.', label='52-Week Highs / Lows')
bullet(doc, 'today\u2019s count of advancing and declining stocks. In a genuinely strong market, advancers should comfortably outnumber decliners.', label='Advance / Decline')
body(doc, 'The Cumulative A/D Line chart shows the running total of the advance/decline balance over the past 20 trading days. A rising line confirms broad participation. A falling line while the index is rising \u2014 called a breadth divergence \u2014 is one of the most reliable early warnings that a rally is losing internal support.')

# ── MARKETS ───────────────────────────────────────────────────────────────────
doc.add_page_break()
h1(doc, '  Markets')

h2(doc, 'UK Fear & Greed Index')
body(doc, 'The Fear & Greed index measures the emotional temperature of the UK stock market. It produces a score from 0 to 100: low scores mean investors are fearful, cautious, and hiding in safe assets; high scores mean they are confident, buying, and taking risk. The score is the equal-weighted average of six underlying signals.')
tbl(doc,
    ['Signal', 'What it is measuring', 'Low score (Fear)', 'High score (Greed)'],
    [
        ['FTSE Momentum',    'FTSE 100 vs its 125-day rolling average',              'Index well below average',    'Index well above average'],
        ['Market Breadth',   '% of FTSE 100 basket above 50-day MA',                'Most stocks in downtrends',   'Most stocks in uptrends'],
        ['VIX',              'US volatility index, inverted',                        'VIX elevated \u2014 nervous', 'VIX low \u2014 calm'],
        ['Safe Haven Demand','20-day return: FTSE 100 vs UK gilt ETF',               'Gilts outperforming stocks',  'Stocks outperforming gilts'],
        ['Realised Vol',     '20-day actual FTSE 100 volatility, inverted',          'High recent volatility',      'Low recent volatility'],
        ['New Highs/Lows',   '% at 52-week highs minus % at 52-week lows',           'More new lows than highs',    'More new highs than lows'],
    ],
    widths=[3.0, 4.5, 2.8, 2.8]
)
body(doc, 'How to use the score in practice:')
bullet(doc, 'Extreme Fear (below 25) has historically corresponded to good buying opportunities. When the market is most fearful, assets are often mispriced downward.', None)
bullet(doc, 'Extreme Greed (above 75) suggests the market is stretched. This is not a signal to sell everything, but a prompt to be selective and avoid overpaying for quality.', None)
bullet(doc, 'The direction of travel matters as much as the level. A score rising from 30 to 45 is more constructive than one falling from 60 to 45, even though both land at the same reading.', None)
note(doc, 'The Fear & Greed index is a sentiment tool, not a timing model. It tells you about the environment you are investing in, not exactly when to act.')

h2(doc, 'Cross-Asset View')
body(doc, 'The Cross-Asset page monitors four indicators that provide context beyond the equity market itself. UK stocks do not move in isolation \u2014 currency moves, commodity prices, and interest rates all affect company earnings and investor behaviour.')
bullet(doc, 'A falling pound makes UK exporters more competitive (overseas revenues convert to more sterling) but raises costs for importers. Large GBP/USD moves can shift the relative appeal of different sectors significantly.', label='GBP/USD')
bullet(doc, 'The oil price directly affects energy company revenues and feeds into input costs across industrials and consumer goods. A sharp fall in oil often signals concern about global demand; a sustained rise is broadly inflationary.', label='Brent Crude')
bullet(doc, 'Gold rises when investors are nervous about inflation, geopolitical risk, or currency stability. A sustained gold rally alongside falling equities is a classic risk-off signal.', label='Gold')
bullet(doc, 'Utilities shares behave somewhat like bonds \u2014 stable dividends, rate-sensitive. This z-score compares their relative performance to gilts. A very negative reading may indicate gilt yields have overshot and rate-sensitive stocks could be due a re-rating.', label='Gilt vs Utilities z-score')

h2(doc, 'UK Gilt Yield Curve')
body(doc, 'The yield curve plots UK government bond (gilt) interest rates across maturities from 2 to 30 years. In normal conditions the curve slopes upward: longer-dated bonds yield more because investors demand extra compensation for lending money over a longer period. When this inverts \u2014 short rates above long rates \u2014 it has historically been one of the most reliable recession indicators available.')
tbl(doc,
    ['Shape', 'What it looks like', 'What it suggests'],
    [
        ['Normal',   '30Y yield clearly above 2Y yield',    'Economy growing; monetary policy broadly neutral'],
        ['Flat',     '30Y and 2Y yields roughly equal',     'Uncertainty; investors unsure about the outlook'],
        ['Inverted', '2Y yield above 10Y or 30Y (in red)',  'Historically associated with recessions; tight policy squeezing growth expectations'],
    ],
    widths=[2.2, 5.3, 8.0]
)
body(doc, 'The history chart lets you trace how the curve has evolved over one to five years. Toggle individual maturities on and off to focus on the parts of the curve that interest you. The 2Y/10Y spread \u2014 the gap between two-year and ten-year yields \u2014 is the most commonly cited inversion signal.')

# ── SIGNAL LOG ────────────────────────────────────────────────────────────────
h1(doc, '  Signal Log')
body(doc, 'Found under Sector Analysis, the Signal Log is a chronological record of events generated by the model, newest first. It is a useful audit trail \u2014 you can see what the model was flagging in recent days and weeks and form your own view of whether those signals proved meaningful.')
tbl(doc,
    ['Badge', 'What triggered it', 'How to interpret it'],
    [
        ['BUY (green)',   'A sector\u2019s RS score broke above 1.05 with the trend rising',    'Consider tilting your screener towards stocks in this sector'],
        ['AVOID (red)',   'A sector\u2019s RS score fell below 0.95 with the trend falling',    'Be cautious about adding new positions in this sector'],
        ['ALERT (amber)', 'Market breadth crossed a significant threshold',                     'Breadth is at an extreme \u2014 check the Breadth page for context'],
        ['INFO (blue)',   'The cycle phase was updated automatically or via the Accept button', 'Records when the cycle model changed phase; informational only'],
    ],
    widths=[2.5, 5.5, 7.5]
)

# ── HOW THE SCORES WORK ───────────────────────────────────────────────────────
doc.add_page_break()
h1(doc, '  How the Scores Work')
body(doc, 'The four composite scores \u2014 Momentum, Quality, Value, and Risk \u2014 each condense a large amount of financial data into a single number for screening and ranking. This section explains the logic behind each one and how to interpret what you see.')

h2(doc, 'Momentum Score (1\u201310)')
body(doc, 'Momentum measures how strongly a stock has been trending relative to its peers. The calculation uses the \u201812-1 month\u2019 window: it looks at the price return from 252 trading days ago to 63 trading days ago, deliberately skipping the most recent three months to avoid picking up short-term reversals.')
body(doc, 'All stocks in the current screened universe are ranked by this return and scored 1\u201310 by percentile. A score of 9 or 10 means the stock is in the top 10\u201320% of momentum performers among the companies currently displayed. Because it is a relative rank, applying a sector filter will shift the scores \u2014 a score of 8 within Technology means something different to a score of 8 across the full All-Share.')
note(doc, 'A high Momentum score means the market has been rewarding this stock \u2014 it says nothing about the quality of the underlying business. Always cross-check with Quality and Value before acting on momentum alone.')

h2(doc, 'Quality Score (0\u201310)')
body(doc, 'Quality tries to identify businesses with durable competitive advantages. It scores companies on five financial ratios that are hallmarks of high-quality businesses, and awards a bonus for each metric that is at or above the company\u2019s own historical median. This means a company that was excellent and is improving scores higher than one that was excellent but is now slipping.')
tbl(doc,
    ['Metric', 'Threshold', 'Why it matters'],
    [
        ['ROIC', '>10%', 'Return on Invested Capital \u2014 how efficiently the whole enterprise, equity and debt combined, generates returns. Sustained high ROIC above the cost of capital is the clearest signal of a genuine competitive advantage.'],
        ['ROE',  '>15%', 'Return on Equity \u2014 how much profit is generated per pound of shareholder equity. High ROE sustained over many years is one of the most reliable quality signals in investing.'],
        ['Gross Margin', '>30%', 'Revenue minus direct costs, as a percentage of revenue. High gross margins indicate pricing power \u2014 customers are willing to pay a premium.'],
        ['Operating Margin', '>10%', 'Profit after operating costs but before interest and tax. Measures operational efficiency and the ability to convert revenue into earnings.'],
        ['FCF Margin', '>5%', 'Free cash flow as a percentage of revenue. Unlike reported profit, FCF cannot easily be manufactured through accounting choices \u2014 it is the cash the business actually produces.'],
    ],
    widths=[3.0, 2.0, 10.5]
)

h2(doc, 'Value Score \u2014 Piotroski F-Score (0\u20139)')
body(doc, 'The Piotroski F-Score does not ask whether a stock is cheap on a price multiple. It asks whether the company\u2019s fundamentals are moving in the right direction. Each of nine binary tests scores 1 (pass) or 0 (fail). A score of 7\u20139 means the business is improving across most dimensions; a score of 0\u20132 means it is deteriorating.')
tbl(doc,
    ['Group', 'What is being tested'],
    [
        ['Profitability',        'Is return on assets positive? Is operating cash flow positive? Is profitability improving year on year? Is cash flow greater than reported profit (a check on earnings quality)?'],
        ['Leverage & Liquidity', 'Is the debt-to-equity ratio falling? Is the current ratio improving? Has the company avoided issuing new shares and diluting existing shareholders?'],
        ['Efficiency',           'Is the gross margin improving? Is asset turnover (revenue per pound of assets) improving?'],
    ],
    widths=[3.5, 12.0]
)
body(doc, 'Setting the Value filter to \u22657 in the screener finds companies whose fundamentals are broadly improving \u2014 often a more reliable signal than raw cheapness on a P/E ratio alone.')

h2(doc, 'Risk Score (1\u201310)')
body(doc, 'The Risk Score combines two independent measures of financial fragility into a single number. Lower is better.')
bullet(doc, '(60% of the score) \u2014 a bankruptcy-prediction model using five accounting ratios. It remains one of the most tested models in corporate finance. Z-Score above 3.0 = financially sound; below 1.8 = distress zone.', label='Altman Z-Score')
bullet(doc, '(40% of the score) \u2014 how much the share price has moved around over the past year, annualised. High volatility reflects a market that is deeply uncertain about the company\u2019s value, which in itself is a risk signal.', label='Annualised Volatility')
tip(doc, 'Use the Risk Score as a filter to shortlist, not as a verdict. A score of 7 means do your homework carefully, not avoid this stock. Always open the Health tab to understand what is driving the number.')

# ── SUGGESTED WORKFLOWS ───────────────────────────────────────────────────────
doc.add_page_break()
h1(doc, '  Suggested Workflows')

h2(doc, 'Morning Market Check  (5 minutes)')
numbered(doc, 1, 'Press \u21bb Market to refresh all live data.')
numbered(doc, 2, 'Check the sidebar: are the FTSE indices up or down? Where is VIX? What is the UK Fear & Greed score and which way is it trending?')
numbered(doc, 3, 'Go to Sector Rotation. Has the heatmap changed since yesterday? Check the Signal Log for any new BUY or AVOID signals.')
numbered(doc, 4, 'Go to Market Breadth. Is the percentage above the 50-day MA rising or falling? Is the A/D line trending up or starting to diverge from the index?')
numbered(doc, 5, 'Search for any existing holdings and check their Chart tab for notable price moves.')

h2(doc, 'Finding New Stock Ideas')
numbered(doc, 1, 'Go to the Screener. Set FTSE Index to your preferred universe (e.g. FTSE 250 for mid-caps).')
numbered(doc, 2, 'Open Advanced. Set Quality \u22656, Value \u22656, Risk \u22645 to find improving, quality businesses with manageable risk.')
numbered(doc, 3, 'Add Momentum \u22656 to focus on stocks the market is already rewarding.')
numbered(doc, 4, 'If a sector shows a BUY signal in the RS table, apply the Sector filter to concentrate there.')
numbered(doc, 5, 'Click through to each result. Start with the Overview and Growth tabs to verify the quality reading, then check Health for balance sheet concerns, then Chart for price context.')

h2(doc, 'Evaluating a Specific Company')
numbered(doc, 1, 'Use the Search box to find the company.')
numbered(doc, 2, 'Chart tab: check the price trend over 1Y and 3Y. Is it in an uptrend? Where is price relative to its moving averages?')
numbered(doc, 3, 'Overview: is the business profitable with strong returns on capital?')
numbered(doc, 4, 'Financials: is revenue growing? Is free cash flow consistently positive and growing?')
numbered(doc, 5, 'Health: what is the Risk Score? Check the Altman Z-Score and the Debt/Equity trend over time.')
numbered(doc, 6, 'Growth: what are the 10-year CAGRs? Are profit margins stable, widening, or compressing?')
numbered(doc, 7, 'Return to the Screener. How do this company\u2019s scores compare to peers in the same sector?')

# ── DATA REFERENCE ────────────────────────────────────────────────────────────
h1(doc, '  Data & Refresh Reference')
tbl(doc,
    ['Data type', 'Source', 'How to refresh'],
    [
        ['Benchmark indices, VIX, FX, commodity prices',  'Live market data, cached 15 min',            'Press \u21bb Market'],
        ['Sector basket prices and Fear & Greed',          'Live market data, cached 15 min',            'Press \u21bb Market'],
        ['Stock price history (charts, momentum scores)',  'Database populated via yfinance',            'Press \u21bb Stock Prices \u2014 run once daily'],
        ['UK gilt yield curve',                            'Bank of England \u2014 fetched on page load', 'Visit the Cross-Asset page'],
        ['Company fundamentals (P/E, margins, etc.)',      'Local database',                             'Updated via separate data import process'],
    ],
    widths=[4.5, 4.5, 6.5]
)
note(doc, 'The Momentum score is calculated from the price history database. If you have not pressed \u21bb Stock Prices today, momentum scores may not reflect the latest price moves.')

# ── APPENDIX: COMPANIES BY SECTOR ────────────────────────────────────────────
doc.add_page_break()
h1(doc, '  Appendix: Companies by Sector')
body(doc, 'The following tables list every company currently in the database, grouped by ICB sector. These are the companies that appear in the Screener and whose sector basket prices are tracked in the sidebar and Sector Analysis pages.')

SECTORS = {
    'Basic Materials': [
        ('AAL.L','Anglo American'),('ANTO.L','Antofagasta'),('ATYM.L','Atalaya Mining Copper'),
        ('BREE.L','Breedon Group'),('CAPD.L','Capital Limited'),('CRDA.L','Croda International'),
        ('ECOR.L','Ecora Royalties'),('ELM.L','Elementis'),('EDV.L','Endeavour Mining'),
        ('ESNT.L','Essentra'),('FXPO.L','Ferrexpo'),('FORT.L','Forterra'),
        ('FRES.L','Fresnillo'),('GLEN.L','Glencore'),('HOC.L','Hochschild Mining'),
        ('IBST.L','Ibstock'),('JMAT.L','Johnson Matthey'),('KMR.L','Kenmare Resources'),
        ('MSLH.L','Marshalls'),('MNDI.L','Mondi'),('PAF.L','Pan African Resources'),
        ('RIO.L','Rio Tinto'),('SYNT.L','Synthomer'),('TET.L','Treatt'),
        ('VSVS.L','Vesuvius'),('VCT.L','Victrex'),('ZTF.L','Zotefoams'),
    ],
    'Communication Services': [
        ('FOUR.L','4imprint Group'),('AAF.L','Airtel Africa'),('AUTO.L','Auto Trader Group'),
        ('BCG.L','Baltic Classifieds Group'),('BMY.L','Bloomsbury Publishing'),('BT-A.L','BT Group'),
        ('FUTR.L','Future'),('GAMA.L','Gamma Communications'),('HTWS.L','Helios Towers'),
        ('INF.L','Informa'),('ITV.L','ITV'),('MONY.L','MONY Group'),
        ('PSON.L','Pearson'),('RCH.L','Reach'),('RMV.L','Rightmove'),
        ('SNWS.L','Smiths News'),('STVG.L','STV Group'),('VOD.L','Vodafone'),
        ('WPP.L','WPP'),
    ],
    'Consumer Cyclical': [
        ('AO.L','AO World'),('ASC.L','ASOS'),('AML.L','Aston Martin Lagonda'),
        ('BTRW.L','Barratt Redrow'),('BWY.L','Bellway'),('BRBY.L','Burberry Group'),
        ('CARD.L','Card Factory'),('CCL.L','Carnival'),('COA.L','Coats Group'),
        ('CPG.L','Compass Group'),('CRST.L','Crest Nicholson'),('CURY.L','Currys'),
        ('DFS.L','DFS Furniture'),('DOM.L','Domino\'s Pizza Group'),('DOCS.L','Dr. Martens'),
        ('DNLM.L','Dunelm Group'),('ENT.L','Entain'),('EVOK.L','Evoke'),
        ('FRAS.L','Frasers Group'),('FSTA.L','Fuller Smith & Turner'),('GAW.L','Games Workshop'),
        ('GRG.L','Greggs'),('HFD.L','Halfords Group'),('HEAD.L','Headlam Group'),
        ('BOWL.L','Hollywood Bowl'),('HSW.L','Hostelworld Group'),('HWDN.L','Howden Joinery'),
        ('INCH.L','Inchcape'),('IHG.L','InterContinental Hotels'),('JDW.L','J D Wetherspoon'),
        ('JD.L','JD Sports Fashion'),('KGF.L','Kingfisher'),('MACF.L','Macfarlane Group'),
        ('MKS.L','Marks and Spencer'),('MARS.L','Marston\'s'),('MER.L','Mears Group'),
        ('MAB.L','Mitchells & Butlers'),('GLE.L','MJ Gleeson'),('MOON.L','Moonpig Group'),
        ('MOTR.L','Motorpoint Group'),('NXT.L','NEXT'),('OTB.L','On the Beach Group'),
        ('PSN.L','Persimmon'),('PETS.L','Pets at Home'),('PTEC.L','Playtech'),
        ('PPH.L','PPHE Hotel Group'),('SSPG.L','SSP Group'),('TW.L','Taylor Wimpey'),
        ('BKG.L','The Berkeley Group'),('GYM.L','The Gym Group'),('RNK.L','The Rank Group'),
        ('THG.L','THG'),('TPT.L','Topps Tiles'),('TRN.L','Trainline'),
        ('VTY.L','Vistry Group'),('WOSG.L','Watches of Switzerland'),('SMWH.L','WH Smith'),
        ('WTB.L','Whitbread'),('WIX.L','Wickes Group'),('XPS.L','XPS Pensions Group'),
    ],
    'Consumer Defensive': [
        ('BAG.L','A.G. Barr'),('AEP.L','AEP Plantations'),('APN.L','Applied Nutrition'),
        ('ABF.L','Associated British Foods'),('BME.L','B&M European Value Retail'),('BATS.L','British American Tobacco'),
        ('BNZL.L','Bunzl'),('CCR.L','C&C Group'),('CCEP.L','Coca-Cola Europacific Partners'),
        ('CCH.L','Coca-Cola HBC'),('CWK.L','Cranswick'),('DGE.L','Diageo'),
        ('FVA.L','Fevara'),('GNC.L','Greencore Group'),('HFG.L','Hilton Food Group'),
        ('IMB.L','Imperial Brands'),('SBRY.L','J Sainsbury'),('MCB.L','McBride'),
        ('OCDO.L','Ocado Group'),('PFD.L','Premier Foods'),('PZC.L','PZ Cussons'),
        ('RKT.L','Reckitt Benckiser'),('TATE.L','Tate & Lyle'),('TSCO.L','Tesco'),
        ('TBTG.L','The Beauty Tech Group'),('ULVR.L','Unilever'),
    ],
    'Energy': [
        ('AT.L','Ashtead Technology'),('BP.L','BP'),('CNE.L','Capricorn Energy'),
        ('DCC.L','DCC'),('ENOG.L','Energean'),('ENQ.L','EnQuest'),
        ('GMS.L','Gulf Marine Services'),('HBR.L','Harbour Energy'),('HTG.L','Hunting'),
        ('ITH.L','Ithaca Energy'),('PHAR.L','Pharos Energy'),('SHEL.L','Shell'),
        ('TLW.L','Tullow Oil'),
    ],
    'Financial Services': [
        ('III.L','3i Group'),('3IN.L','3i Infrastructure'),('AAIF.L','Aberdeen Asian Income Fund'),
        ('ABDN.L','Aberdeen Group'),('ADM.L','Admiral Group'),('AJB.L','AJ Bell'),
        ('ASHM.L','Ashmore Group'),('AV.L','Aviva'),('BNKR.L','Bankers Investment Trust'),
        ('BARC.L','Barclays'),('BEZ.L','Beazley'),('BHMG.L','BH Macro'),
        ('BSIF.L','Bluefield Solar Income Fund'),('BPT.L','Bridgepoint Group'),('BRK.L','Brooks Macdonald'),
        ('CABP.L','CAB Payments'),('CSN.L','Chesnara'),('CHRY.L','Chrysalis Investments'),
        ('CLIG.L','City of London Investment Group'),('CBG.L','Close Brothers'),('CMCX.L','CMC Markets'),
        ('NCYF.L','CQS New City High Yield Fund'),('CTUK.L','CT UK Capital & Income IT'),('CVCG.L','CVC Income & Growth'),
        ('DGI9.L','Digital 9 Infrastructure'),('EWI.L','Edinburgh Worldwide IT'),('FEML.L','Fidelity Emerging Markets'),
        ('FSV.L','Fidelity Special Values'),('FGEN.L','Foresight Environmental Infrastructure'),('FSG.L','Foresight Group'),
        ('FSFL.L','Foresight Solar Fund'),('FCH.L','Funding Circle'),('GABI.L','GCP Asset Backed Income'),
        ('GCP.L','GCP Infrastructure Investments'),('HVPE.L','HarbourVest Global Private Equity'),('HFEL.L','Henderson Far East Income'),
        ('HICL.L','HICL Infrastructure'),('HSX.L','Hiscox'),('HSBA.L','HSBC'),
        ('ICG.L','ICG'),('IGG.L','IG Group'),('IGC.L','India Capital Growth Fund'),
        ('IHP.L','IntegraFin'),('IPF.L','International Personal Finance'),('INPP.L','International Public Partnerships'),
        ('BIPS.L','Invesco Bond Income Plus'),('INVP.L','Investec'),('IPO.L','IP Group'),
        ('JARA.L','JPMorgan Global Core Real Assets'),('JFJ.L','JPMorgan Japanese IT'),('JTC.L','JTC'),
        ('JUP.L','Jupiter Fund Management'),('JUST.L','Just Group'),('LRE.L','Lancashire Holdings'),
        ('LGEN.L','Legal & General'),('LTI.L','Lindsell Train IT'),('BGEO.L','Lion Finance Group'),
        ('LIO.L','Liontrust Asset Management'),('LLOY.L','Lloyds Banking Group'),('LSEG.L','London Stock Exchange Group'),
        ('MNG.L','M&G'),('EMG.L','Man Group'),('MTRO.L','Metro Bank'),
        ('NWG.L','NatWest Group'),('NBPE.L','NB Private Equity Partners'),('NESF.L','NextEnergy Solar Fund'),
        ('N91.L','Ninety One'),('OCI.L','Oakley Capital Investments'),('OIG.L','Oryx International Growth'),
        ('OSB.L','OSB Group'),('PAG.L','Paragon Banking Group'),('PEY.L','Partners Group Private Equity'),
        ('PBEE.L','PensionBee'),('PSH.L','Pershing Square Holdings'),('PLUS.L','Plus500'),
        ('PCFT.L','Polar Capital Global Financials Trust'),('POLN.L','Pollen Street Group'),('PRU.L','Prudential'),
        ('QLT.L','Quilter'),('RAT.L','Rathbones Group'),('RECI.L','Real Estate Credit Investments'),
        ('REC.L','Record'),('RSE.L','Riverstone Energy'),('RTW.L','RTW Biotech Opportunities'),
        ('RICA.L','Ruffer Investment Company'),('SUS.L','S&U'),('SBRE.L','Sabre Insurance'),
        ('SAGA.L','Saga'),('SDR.L','Schroders'),('STB.L','Secure Trust Bank'),
        ('SEQI.L','Sequoia Economic Infrastructure'),('SHAW.L','Shawbrook Group'),('STJ.L','St. James\'s Place'),
        ('STAN.L','Standard Chartered'),('SDLF.L','Standard Life'),('SYNC.L','Syncona'),
        ('TBCG.L','TBC Bank Group'),('TCAP.L','TP ICAP Group'),('TFIF.L','TwentyFour Income Fund'),
        ('SMIF.L','TwentyFour Select Monthly Income'),('UEM.L','Utilico Emerging Markets'),('VANQ.L','Vanquis Banking'),
        ('VEIL.L','Vietnam Enterprise IT'),('VNH.L','VietNam Holding'),('VOF.L','VinaCapital Vietnam Opportunity'),
        ('WWH.L','Worldwide Healthcare IT'),
    ],
    'Healthcare': [
        ('AZN.L','AstraZeneca'),('CTEC.L','ConvaTec'),('GNS.L','Genus'),
        ('GSK.L','GSK'),('HLN.L','Haleon'),('HIK.L','Hikma Pharmaceuticals'),
        ('IBT.L','International Biotechnology Trust'),('OXB.L','Oxford Biomedica'),('ONT.L','Oxford Nanopore Technologies'),
        ('PRTC.L','PureTech Health'),('SN.L','Smith & Nephew'),('SPI.L','Spire Healthcare'),
    ],
    'Industrials': [
        ('AVON.L','Avon Technologies'),('BAB.L','Babcock International'),('BA.L','BAE Systems'),
        ('BBY.L','Balfour Beatty'),('BOY.L','Bodycote'),('BMS.L','Braemar'),
        ('CPI.L','Capita'),('CWR.L','Ceres Power'),('CHG.L','Chemring Group'),
        ('CKN.L','Clarkson'),('COST.L','Costain Group'),('DPLM.L','Diploma'),
        ('EZJ.L','easyJet'),('ELIX.L','Elixirr International'),('ECEL.L','Eurocell'),
        ('EXPN.L','Experian'),('FGP.L','FirstGroup'),('GFRD.L','Galliford Try'),
        ('GEN.L','Genuit Group'),('GDWN.L','Goodwin'),('GFTU.L','Grafton Group'),
        ('HLMA.L','Halma'),('HAS.L','Hays'),('HILS.L','Hill & Smith'),
        ('IMI.L','IMI'),('IAG.L','Intl Consolidated Airlines'),('ITRK.L','Intertek Group'),
        ('FSJ.L','James Fisher and Sons'),('JSG.L','Johnson Service Group'),('KLR.L','Keller Group'),
        ('KIE.L','Kier Group'),('LUCE.L','Luceco'),('MEGP.L','ME Group International'),
        ('MRO.L','Melrose Industries'),('MTO.L','Mitie Group'),('MCG.L','Mobico Group'),
        ('MGAM.L','Morgan Advanced Materials'),('MGNS.L','Morgan Sindall Group'),('NXR.L','Norcros'),
        ('PAGE.L','PageGroup'),('PRV.L','Porvair'),('QQ.L','QinetiQ Group'),
        ('REL.L','RELX'),('RTO.L','Rentokil Initial'),('RHIM.L','RHI Magnesita'),
        ('RWA.L','Robert Walters'),('RR.L','Rolls-Royce'),('ROR.L','Rotork'),
        ('RS1.L','RS Group'),('SNR.L','Senior'),('SRP.L','Serco Group'),
        ('SFR.L','Severfield'),('SHI.L','SIG'),('SMIN.L','Smiths Group'),
        ('SDY.L','Speedy Hire'),('SPX.L','Spirax Group'),('STEM.L','SThree'),
        ('TMIP.L','Taylor Maritime'),('WEIR.L','The Weir Group'),('TPK.L','Travis Perkins'),
        ('TRI.L','Trifast'),('FAN.L','Volution Group'),('VP.L','Vp'),
        ('WIZZ.L','Wizz Air'),('XPP.L','XP Power'),('ZIG.L','Zigup'),
    ],
    'Real Estate': [
        ('BYG.L','Big Yellow Group'),('BLND.L','British Land'),('CLI.L','CLS Holdings'),
        ('DLN.L','Derwent London'),('FOXT.L','Foxtons Group'),('GRI.L','Grainger'),
        ('GPE.L','Great Portland Estates'),('HMSO.L','Hammerson'),('HWG.L','Harworth Group'),
        ('HLCL.L','Helical'),('BOOT.L','Henry Boot'),('IWG.L','International Workplace Group'),
        ('LAND.L','Land Securities'),('LMP.L','LondonMetric Property'),('LSL.L','LSL Property Services'),
        ('NRR.L','NewRiver REIT'),('PCA.L','Palace Capital'),('PSDL.L','Phoenix Spree Deutschland'),
        ('PCTN.L','Picton Property Income'),('PHP.L','Primary Health Properties'),('RGL.L','Regional REIT'),
        ('SAFE.L','Safestore'),('SVS.L','Savills'),('SREI.L','Schroder Real Estate IT'),
        ('SGRO.L','SEGRO'),('SHC.L','Shaftesbury Capital'),('SRE.L','Sirius Real Estate'),
        ('SUPR.L','Supermarket Income REIT'),('UTG.L','Unite Group'),('WKP.L','Workspace Group'),
    ],
    'Technology': [
        ('ALFA.L','Alfa Financial Software'),('APTD.L','Aptitude Software'),('ATG.L','Auction Technology Group'),
        ('BYIT.L','Bytes Technology Group'),('CCC.L','Computacenter'),('DSCV.L','discoverIE Group'),
        ('FDM.L','FDM Group'),('GBG.L','GB Group'),('KNOS.L','Kainos Group'),
        ('NCC.L','NCC Group'),('OXIG.L','Oxford Instruments'),('PAY.L','PayPoint'),
        ('PINE.L','Pinewood Technologies'),('RPI.L','Raspberry Pi'),('RSW.L','Renishaw'),
        ('RM.L','RM'),('SCT.L','Softcat'),('SGE.L','The Sage Group'),
        ('TRST.L','Trustpilot Group'),('TTG.L','TT Electronics'),('VID.L','Videndum'),
        ('EWG.L','W.A.G Payment Solutions'),('XAR.L','Xaar'),
    ],
    'Utilities': [
        ('CNA.L','Centrica'),('DRX.L','Drax Group'),('MTLN.L','Metlen Energy & Metals'),
        ('NG.L','National Grid'),('PNN.L','Pennon Group'),('SVT.L','Severn Trent'),
        ('SSE.L','SSE'),('TEP.L','Telecom Plus'),('TRIG.L','The Renewables Infrastructure Group'),
        ('UU.L','United Utilities'),
    ],
}

def sector_table(doc, companies):
    # Two side-by-side columns of ticker | name, rendered as a 4-col table
    rows_out = []
    pairs = list(companies)
    for i in range(0, len(pairs), 2):
        left  = pairs[i]
        right = pairs[i+1] if i+1 < len(pairs) else ('', '')
        rows_out.append([left[0], left[1], right[0], right[1]])

    t = doc.add_table(rows=1+len(rows_out), cols=4)
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_borders(t, color='DDDDEE', sz='2')

    # Header
    hr = t.rows[0]
    hdr_texts = ['Ticker', 'Company', 'Ticker', 'Company']
    for i, ht in enumerate(hdr_texts):
        c = hr.cells[i]; shade_cell(c, NAVY2); cell_margins(c, 70, 70, 100, 100)
        p = c.paragraphs[0]; r = p.add_run(ht)
        r.bold=True; r.font.size=Pt(8.5); r.font.color.rgb=ORANGE; r.font.name='Calibri'
        p.paragraph_format.space_before=Pt(0); p.paragraph_format.space_after=Pt(0)

    for ri, rd in enumerate(rows_out):
        bg = ROW_ALT if ri%2==0 else ROW_WHT
        row = t.rows[ri+1]
        for ci, val in enumerate(rd):
            c = row.cells[ci]; shade_cell(c, bg); cell_margins(c, 60, 60, 100, 100)
            p = c.paragraphs[0]
            r = p.add_run(str(val))
            r.font.size=Pt(8.5); r.font.name='Calibri'
            # ticker cols bold
            if ci in (0, 2):
                r.bold=True; r.font.color.rgb=NAVY
            else:
                r.font.color.rgb=TEXT
            p.paragraph_format.space_before=Pt(0); p.paragraph_format.space_after=Pt(0)

    # column widths: ticker narrow, name wider, gap col, ticker, name
    widths_cm = [1.8, 6.2, 1.8, 6.2]
    for row in t.rows:
        for ci, w in enumerate(widths_cm):
            row.cells[ci].width = Cm(w)

    doc.add_paragraph().paragraph_format.space_after = Pt(2)

for sector_name, companies in SECTORS.items():
    h2(doc, f'{sector_name}  ({len(companies)} companies)')
    sector_table(doc, companies)

# ── SAVE ──────────────────────────────────────────────────────────────────────
out = r'C:/Users/richa/Documents/WebProjects/UK_stocks/stock_screener/Egg_Basket_User_Guide.docx'
doc.save(out)
print('Saved:', out)
