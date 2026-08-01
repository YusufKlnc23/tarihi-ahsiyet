# Tarih PDF Analyzer

Turk tarihi kaynaklarini PDF veya elle hazirlanmis TXT chunk'lari olarak PostgreSQL'e alir. Yeni urun yonu, bu kaynaklari tarihi sahsiyetler uzerinden kaynakli chatbox deneyimine cevirmektir.

## Kurulum

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

PostgreSQL baglantisi:

```powershell
$env:DATABASE_URL="postgresql://postgres:SIFREN@localhost:5432/tarih_figures"
tarih-analyze init-db
```

LLM cevabi icin:

```powershell
$env:OPENAI_API_KEY="..."
$env:OPENAI_MODEL="gpt-4o-mini"
```

## Veri Akisi

PDF/TXT kaynaklari:

```powershell
tarih-analyze ingest data/pdfs
```

`data/pdfs` altindaki `.pdf` dosyalari PDF okuyucuyla, `.txt` dosyalari ise standalone metin kaynagi olarak chunk'lara ayrilir.
Secilebilir metin icermeyen PDF'ler OCR gerektirdigi icin `OCR_SKIPPED` olarak atlanir; bu dosyalari yayin oncesi OCR'dan gecirip tekrar ingest etmek gerekir.

Elle bolunmus TXT chunk'lari:

```text
data/texts/ornek-kitap/
  metadata.json
  chunk-001.txt
  chunk-002.txt
```

`metadata.json`:

```json
{
  "title": "Ornek Kitap",
  "author": "Ornek Yazar",
  "year": 2026,
  "chunks": [
    {"file": "chunk-001.txt", "pages": "1-10"},
    {"file": "chunk-002.txt", "start_page": 11, "end_page": 20}
  ]
}
```

Yukleme:

```powershell
tarih-analyze ingest-text data/texts
```

## Sahsiyet Chatbox

Sahsiyet listesini yukle:

```powershell
tarih-analyze load-figures data/figures.example.json
tarih-analyze list-figures
```

CLI uzerinden kaynakli soru sor:

```powershell
tarih-analyze ask-figure --figure-id 1 --question "Bu kaynaklarda nasil degerlendiriliyor?"
```

LLM kullanmadan kaynak eslesmesini test etmek icin:

```powershell
tarih-analyze ask-figure --figure-id 1 --question "Siyasi rolu nedir?" --mock
```

Gradio chatbox:

```powershell
python app.py
```

Adres:

```text
http://127.0.0.1:7860
```

Chatbox secilen sahsiyetin adini ve alias'larini chunk metinlerinde arar, ilgili kaynak parcalarini bulur ve LLM'e yalnizca bu parcalara dayanarak cevap urettirir. Kaynak bulunamazsa cevap uydurmaz.
Sahsiyet secmeden soru sorulursa tum chunk kaynaklarinda arama yapar.

## MCP Server

MCP istemcilerine temel kaynakli soru-cevap araclari acmak icin opsiyonel kurulum:

```powershell
python -m pip install -e ".[mcp]"
tarih-mcp-server
```

Sunulan araclar:

- `list_figures`: PostgreSQL'deki tarihi sahsiyetleri listeler.
- `ask_figure`: Secili sahsiyet icin kaynakli cevap dondurur.
- `search_sources`: Tum kaynak chunk'lari icinde arama yapar.

## PostgreSQL Tablolari

Kaynak katmani:

- `books`
- `pages`
- `chunks`

Sahsiyet/chat katmani:

- `historical_figures`
- `figure_aliases`
- `figure_mentions`
- `chat_sessions`
- `chat_messages`

`figure_mentions` su an iskelet olarak var. Otomatik kisi cikarma sonraki adimda bu tabloyu doldurabilir.

## Yayinlama Notu

PDF'ler, manuel metin chunk'lari, uretilen raporlar, `.env`, sanal ortam ve cache klasorleri `.gitignore` ile disarida tutulur. GitHub'a kaynak PDF veya ozel not koymayin.

Yayin oncesi minimum kontrol:

```powershell
python -m pytest -q
tarih-analyze init-db
tarih-analyze load-figures data/figures.example.json
tarih-analyze ingest data/pdfs
python app.py
```

## Sinirlar

- OCR v1 kapsaminda degil.
- Ilk sahsiyet chat retrieval'i basit PostgreSQL `ILIKE` aramasidir.
- Daha iyi cevap kalitesi icin sonraki adim `pgvector + embeddings` olmalidir.
- LLM'e gonderilen kaynak metinler icin telif/gizlilik sorumlulugu kullanicidadir.
