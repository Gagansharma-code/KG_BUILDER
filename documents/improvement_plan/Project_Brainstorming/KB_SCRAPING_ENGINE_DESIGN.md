# OpenForge — Knowledge Base Scraping Engine Design

**Document Version:** 1.0
**Status:** Design Only — No Implementation
**Scope:** Source retrieval strategy + major population run definition

---

## Part 1: Source Retrieval Map

### 1.1 Manufacturer Datasheets (Critical)

Fallback chain per component:

```
Nexar GraphQL API  →  Manufacturer Direct CDN  →  Aggregator (Mouser/DigiKey)  →  Community fallback  →  Manual queue
```

Nexar (already in OpenForge) returns a PDF URL for most components. That is the primary path.

Manufacturer-direct fallbacks when Nexar misses:

| Manufacturer | Direct Access Method |
|---|---|
| TI | `product.ti.com` REST API + `ti.com/lit/ds/` CDN |
| ADI | `analog.com` product search API + media CDN |
| STMicro | `st.com` product catalog API |
| NXP | `nxp.com` product page scrape |
| Infineon | `infineon.com` product page scrape |
| Microchip | `microchip.com` product page scrape |

Aggregator fallback: Mouser and DigiKey both expose datasheet links per part number — scrapable or via their APIs.

Last fallback: `alldatasheet.com`, `datasheetarchive.com` — scrape only.

---

### 1.2 KiCad Libraries (Critical)

Direct GitHub API. Three repos:

- `KiCad/kicad-symbols`
- `KiCad/kicad-footprints`
- `KiCad/kicad-packages3D`

Download via GitHub zipball or `git clone`. No auth needed. Update via `git pull` on a schedule.

---

### 1.3 SnapEDA / Ultra Librarian (Medium)

- SnapEDA has a REST API (requires free API key) — returns symbol + footprint per part number
- Ultra Librarian is web-only, requires account — scrape or skip for now

---

### 1.4 App Notes and Reference Designs (High)

Same path as datasheets — Nexar returns these too if queried by document type. TI and ADI also have dedicated app note portals scrapable by part family.

---

### 1.5 Standards — IPC, JEDEC (Medium)

| Standard Body | Status |
|---|---|
| JEDEC | Partial free — `jedec.org/free-downloads`, scrapable |
| IPC | Most paywalled — manual ingestion only |
| IEEE | Fully paywalled — out of scope |

---

### 1.6 Community — GitHub, Stack Exchange (Low)

- GitHub REST API — search by topic (`pcb`, `kicad`, `eagle`)
- Stack Exchange API — `electronics.stackexchange.com`
- Both rate-limited, both low priority. Defer until core sources are covered.

---

### 1.7 Adapter Interface

Each source above becomes one Source Adapter — a module with a fixed interface:

```
given(part_number or query) → returns (pdf_url or file_path or None)
```

The scraping engine calls adapters in fallback order. First non-None result wins.

---

## Part 2: Major Population Run

Three driving signals determine what to download: what every PCB needs, what Nexar's popularity data confirms is actually used, and what the scientist prompt gap log explicitly requires.

---

### Tier 1 — Universal Seed Corpus

Every PCB regardless of domain touches these categories. Download top 50–100 parts per category per major manufacturer (TI, ADI, ST, NXP, Infineon, Microchip).

**Source for this list:** Query Nexar's top-N-by-category — it returns parts ranked by actual search volume. Do not guess popularity; let Nexar's data decide which parts to pull.

| Category | Rationale |
|---|---|
| LDO linear regulators | Every board has power |
| Buck converters | Every board has power |
| Boost / inverting converters | Common power variant |
| Voltage references | Every precision design |
| Power supervisors / monitors | Common in embedded |
| General-purpose op-amps | Ubiquitous |
| Precision / zero-drift op-amps | Scientist prompts confirm need |
| Instrumentation amplifiers | Measurement boards |
| Comparators | Ubiquitous |
| ADCs (SAR + sigma-delta) | Nearly every sensing board |
| DACs | Common in control / RF |
| Logic buffers / level shifters | Every mixed-voltage board |
| UART / SPI / I2C bridges | Interface standard |
| USB-UART bridges | Every USB board |
| CAN / RS-485 transceivers | Industrial / defense standard |
| TVS / ESD protection | Every board needs it |
| Gate drivers | Every switching design |
| MOSFETs (signal + power) | Ubiquitous switches |
| BJTs | Still everywhere |
| Crystal oscillators | Every clocked design |

---

### Tier 2 — KiCad Library Sweep

Download datasheets for every part in the official KiCad standard library. These are curated by the community as parts people actually use. Nexar batch-query the part numbers; anything Nexar misses falls to manufacturer direct.

Estimated scope: 8,000–12,000 parts.

---

### Tier 3 — App Notes by Topology

Not component datasheets — design recipes for KG-2. One canonical app note per major topology.

| Topology | Source Documents |
|---|---|
| LDO design | TI SLVA477, ADI AN-1378 |
| Synchronous buck | TI SLVA477, TI SNVA786 |
| Precision current source | TI SBOA327, TI SBOA273, ADI AN-1357 |
| Bias tee | Minicircuits + ADI RF notes |
| Instrumentation amp | ADI AN-1321 |
| Precision ADC layout | TI SLYT583, ADI MT-031 |
| USB-C power delivery | TI SLVAE57 |
| CAN bus design | TI SLLA270 |
| EMC / decoupling | TI SLOA114 |
| Op-amp stability | TI SLOA049 |

---

### Tier 4 — Scientist Prompt Gap Fill

Directly from the BUILD REQUIREMENTS backlog. These are confirmed missing and block real prompts already received.

| Document | Gap ID | Priority |
|---|---|---|
| Libbrecht & Hall 1993 paper (Rev. Sci. Instrum. 64, 2133) | GAP-001-A | HIGH |
| TI SBOA327 — Precision Current Source Design | GAP-001-A | HIGH |
| TI SBOA273 — Low-Noise Current Source Techniques | GAP-001-A | HIGH |
| ADI AN-1357 — Precision Current Sources and Sinks | GAP-001-A | HIGH |
| OPA189 datasheet (TI) | GAP-001-B | HIGH |
| ADA4522-2 datasheet (ADI) | GAP-001-B | HIGH |
| AD8628 datasheet (ADI) | GAP-001-B | HIGH |
| OPA2188 datasheet (TI) | GAP-001-B | HIGH |
| Vishay VSR series datasheet | GAP-001-C | MEDIUM |
| Susumu RG2012N series datasheet | GAP-001-C | MEDIUM |
| Caddock MP915 datasheet | GAP-001-C | MEDIUM |
| Bourns 3590S datasheet | GAP-001-E | LOW |
| Vishay P11 series datasheet | GAP-001-E | LOW |
| ZCOM 4596 VCO datasheet | GAP-002-B | HIGH |
| USB-UART bridge datasheets + app notes | GAP-002-D | HIGH |
| Bias tee component datasheets + app notes | GAP-002-C | HIGH |
| DAC + VTune interface app notes | GAP-002-E | MEDIUM |

---

### Tier 5 — Family Expansion Rule (Runtime, Not Batch)

When any part from a family is hit during a design and is missing from KG-3, automatically queue the rest of that family for ingestion.

Example: OPA189 requested → queue OPA188, OPA2188, OPA4188.

This keeps the corpus growing without bloating the initial population run.

---

### What NOT to Download

| Content | Reason |
|---|---|
| Full IPC / JEDEC standards | Mostly paywalled; manual only for free subset |
| IEEE papers | Fully paywalled, out of scope |
| Community forums / Stack Exchange | Too low signal-to-noise for batch |
| Obscure / EOL parts | On-demand only, triggered by a design prompt miss |
| Ultra Librarian | Web-only, low priority — defer |

---

### Execution Order

```
1. Nexar batch      → Tier 1 (popularity-ranked per category)
2. Nexar batch      → Tier 2 (KiCad library part numbers)
3. Manufacturer     → Tier 3 (app notes, not in Nexar)
   direct + scrape
4. Manual ingest    → Tier 4 (gap fill, specific named documents)
5. Runtime rule     → Tier 5 (family expansion, ongoing)
```
