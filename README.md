# Cnc-Assistant

Tabakaya dizilmis vektorleri (DXF) ve hazir G-Code dosyalarini, **olculere hic
dokunmadan** CNC tabaka kesimine hazirlayan bir Python aracidir.

Uc isi bir arada yapar:

1. **Baslangic (lead-in) noktasi optimizasyonu** — her kapali vektorun kesim
   baslangicini, parca kesilirken **her zaman destegi kalacak** sekilde
   konumlandirir.
2. **Gereksiz node temizligi** — vektorlerin uzerindeki fazla (es-dogrultulu)
   noktalari, **sekli %100 koruyarak** kaldirir; boylece ArtCAM vb.
   yazilimlarda dosya hafifler ve gereksiz node kalabaligi ortadan kalkar.
3. **G-Code blok siralama** — hazir G-Code'daki kesim bloklarini siralar.
   **Icerme (nesting) her zaman birincil kuraldir:** bir "O" harfinin
   gobegindeki tum vektorler dis konturdan **%100 once** kesilir. Ayni derinlik
   seviyesinde ise malzeme destekte kalacak sekilde **sol-alttan sag-uste**
   dizilir. Otomatik yapabildigi gibi, **web arayuzu** veya **etkilesimli
   terminal editoru** ile elle de duzenlenebilir (geri alma + canli onizleme).

4. **Web arayuzu** — parametreleri ayarlayip **anlik** onizleme goren, G-Code
   siralamasini surukleyerek/`59 60` yazarak duzenleyen, klasorleri tek tusla
   toplu isleyen bir tarayici arayuzu. **Hicbir ek kutuphane gerektirmez**
   (Python standart kutuphanesi + ezdxf).

> Tasarim ilkesi: **olculer asla degismez.** Her DXF cikti dosyasi, kaydedildikten
> sonra orijinaliyle (bounding box + toplam cevre uzunlugu) otomatik karsilastirilir;
> en ufak geometrik sapma uyari verir.

---

## Kurulum

```bash
# Zorunlu
pip install ezdxf

# Onizleme (oncesi/sonrasi + sira gorselleri) icin onerilir
pip install matplotlib

# veya hepsi birden:
pip install -r requirements.txt

# paket olarak kurmak isterseniz (cnc-assistant komutu olusur):
pip install -e .
```

Python 3.8+ gerektirir.

---

## Hizli baslangic

```bash
# WEB ARAYUZU (onerilir) - tarayicida acilir
python main.py --web
python main.py --web --port 8000

# DXF: node temizligi + baslangic optimizasyonu + risk uyarisi + onizleme
python main.py tabaka.dxf

# G-Code: otomatik yeniden siralama (icerme-oncelikli + sol-alt -> sag-ust)
python main.py kesim.tap

# G-Code: ETKILESIMLI (canli) terminal editoru
python main.py kesim.tap -e

# BIR KLASOR ver -> icindeki her sey otomatik, ayri dizinlere islenir
python main.py /yol/klasor --proje musteriA

# Birden fazla dosya ayni anda (mod uzantidan otomatik secilir)
python main.py a.dxf b.tap c.nc

# Tum secenekler
python main.py --help
```

Paket kurduysaniz `python main.py` yerine `cnc-assistant` komutunu da
kullanabilirsiniz.

Denemek icin ornek dosyalar uretin:

```bash
python examples/ornek_uret.py
python main.py examples/ornek_tabaka.dxf
python main.py examples/ornek_kesim.tap -e
```

---

## Ne yapar? (detay)

### 1) Baslangic noktasi optimizasyonu (DXF) — SOL-UST HEDEF yontemi

Baslangici parcanin **UST kenarina, soldan ~%20** (sol-ust bolge) tasiriz.
Bu, operatorun ArtCAM'de **elle** yaptigi "manuel optimize" yerlesiminin
birebir karsiligidir: baslangic ust kenarda, keskin kose degil, kesim boyunca
destegi korunan bir noktaya oturur.

Yontem (yon-projeksiyonu degil, **hedef-nokta yakinligi**): ust bant icindeki
(bbox yuksekliginin ~%30'u kadar ust) vertex'ler arasindan yatayda hedefe en
yakin olan secilir. Hedefe yeterince yakin **mevcut** bir vertex varsa o
kullanilir (yeni node yok); yoksa ust kenarin **duz segmenti uzerine TAM
hedefte** tek bir lead-in node'u eklenir (ArtCAM'in yaptigi gibi). Boylece sade
dikdortgen parcalarda bile baslangic sol-ust ~%20 noktaya oturur; **sekil (bbox
+ toplam cevre) %100 korunur.** `--destek-yonu ...` ile bant/hedef degistirilse
de **4 vertex'li kucuk parcada da, 900+ vertex'li karmasik parcada da** ayni
guvenle calisir.

Uzun-ince **dikey seritler** sol yan kenarda (ucundan ~%25 iceride, iki uctan
destekli) baslar; **yatay seritler** ve cemberler ust kenar (sol-ust) kuralini
izler. Node ekleme `nokta_ekle=False` ile kapatilabilir (yalnizca mevcut vertex).

Hedef `--destek-yonu` ile ayarlanir: **`sol-ust`** (varsayilan, onerilen —
elle-optimize dosyasina en yakin), `ust` (orta-ust) veya `sag-ust`.

> Gercek bir ArtCAM nesting dosyasinda (1500×3000, 262 parca) test edildi:
> algoritma ciktisi, operatorun **elle optimize** ettigi dosyaya, operatorun
> yerini fiilen degistirdigi parcalarin **~%71'inde** birebir (normalize mesafe
> < 0.12) oturdu; ortalama sapma sol-ust hedefte 0.14, eski sag-ust surumde
> 0.77 idi. bbox + toplam cevre birebir korundu.

### 2) Gereksiz node temizligi

Baslangic noktasi belirlenmeden **once**, vektorlerin uzerindeki gereksiz
node'lar temizlenir. Bir nokta yalnizca su sartlarda silinir:

- komsu iki segment de **duz** (yay degil),
- nokta komsulariyla **es-dogrultulu** ve aralarinda,
- nokta **genislik/taper tasimiyor**.

Bu, cevreyi ve bbox'u degistirmez — sadece nokta sayisini azaltir. Kapatmak
icin `--node-temizleme-yok`, toleransi ayarlamak icin `--node-tol`.

### 3) Riskli parca uyarisi

Tabaka olcusu otomatik tespit edilir; alan/boyut esigini asan buyuk parcalar
konsola loglanir ve onizlemede **kirmizi** gosterilir (hold-down vidasi
onerisi). DXF'e cizim **eklenmez**. Esikler: `--alan-orani`, `--boyut-orani`.

### 4) G-Code blok siralama

Mevcut G-Code satirlari **aynen** korunur; yalnizca bagimsiz kesim bloklarinin
**sirasi** degisir.

**Icerme (nesting) onceligi — %100 garanti.** Bir blogun konturu baska bir
blogun konturunun *icinde* ise (bbox icerme + agirlik-merkezi ray-casting testi
ile tespit edilir), ictekiler her zaman **once** kesilir. Bir "O" harfinin
gobegindeki 100 vektor, O'nun dis konturundan kesinlikle once islenir. Bu,
secilen travel stratejisinden **bagimsiz** birincil kuraldir; en icteki
(derinligi en yuksek) seviyeden disa dogru ilerlenir. Elle siralamada bu kural
ihlal edilirse arayuz/terminal **kirmizi uyari** verir.

Ayni derinlik seviyesindeki bloklar arasinda travel stratejisi:
- **Varsayilan:** sol-alttan sag-uste (destek korumali).
- `--serpantin`: zigzag (bosta tasimayi azaltir).
- `--engel`: engel-farkindalikli (uzerine uzanan parcayi once temizler).

---

## Web arayuzu

```bash
python main.py --web           # http://127.0.0.1:8000 acilir
```

Arayuz sade, modern bir tasarima sahiptir (acik/koyu tema otomatik; sag ustteki
◐ ile degistirilebilir) ve saf HTML/JS'tir (SVG ile cizim) — onizlemeler
**anlik** ve tarayici tarafinda uretilir. Tarayici **otomatik acilmaz** (adres
konsola yazilir); istenirse `--web --tarayici-ac`.

**v1.2 yenilikleri (hepsi arayuzde):**
- **Dosya gezgininde arama/filtre** ve alt klasorler icin **icerik sayaci**
  (magenta `T{gcode}` toolpath + sari `V{dxf}` vektor; bossa gizli).
- **Cok sekmeli calisma** + **surukle-birak** ile dosya yukleme.
- **Gercek takim yolu onizlemesi:** G2/G3 **yaylar** chord degil gercek egri
  cizilir.
- **Koprü (tab) isaretleme:** kontur basina esit araliklı, koseden kacinan
  koprü konumlari (turuncu) — kesim geometrisi degismez, sadece "nereye koprü"
  gosterilir (ArtCAM'de/elde koprü buraya konur).
- **Yerlesim (nesting):** parcalari tabakaya raf algoritmasiyla dizer; parca
  yalnizca otelenir, sekil/olcu %100 korunur.
- **Boşta-yol karsilastirmasi:** her siralama modunun tasima mesafesi cip olarak
  gosterilir, en kisa olan yesil vurgulanir (tiklayinca uygulanir).
- **Birim gostergesi** (mm/inch, G20/G21'den), **birlesik toplu-isleme
  tablosu**, **Tumunu Kaydet**, **klavye kisayollari** (Ctrl+S, Ctrl+Shift+S,
  Ctrl+Z/Y, Ctrl+W, Ctrl+1..9) ve **ayar hatirlama** (tema, parametreler,
  son klasor - localStorage).

**v1.7 yenilikleri:**
- **Gercek NFP + Genetik nesting motoru** (`nesting_nfp.py`, pyclipper): No-Fit
  Polygon (Minkowski) geometrisi ile parca-parca cakisma, Inner-Fit ile
  konteyner icinde tutma, ve **genetik algoritma** (order-crossover + mutasyon
  + elitizm) ile sira/rotasyon optimizasyonu. Genelde raster'dan **daha iyi
  doluluk**. Nesting panelinde **Motor** secici (Raster (hizli) / NFP+Genetik
  (kaliteli)) + GA populasyon/nesil ayarlari. pyclipper yoksa otomatik raster'a
  doner.
- **Web gezgininde klasor islemleri:** "+ Klasor" ile olusturma, her klasorde
  ✎ yeniden adlandirma ve 🗑 silme (yol-gezme engelli, ev/kok korumali).

**v1.6 yenilikleri:**
- **Vektorel PDF disari aktarma:** DXF onizlemesinde "PDF (vektorel)" butonu
  ONCESI+SONRASI panellerini gercek bezier egrileriyle tek PDF olarak indirir
  (sonsuz yaklastirmada net).
- **Gelismis Nesting sekmesi** (ust bardaki ⊞ Nesting): gercek-sekil (raster)
  yerlesim. Parcalar DXF'ten (her kapali kontur) veya olcu vererek
  (dikdortgen/daire) + ADET; tabakalar **coklu** ve **sabit dikdortgen/daire ya
  da bir DXF'ten alinan HERHANGI bir sekil** (ArtCAM'in aksine dikdortgen sart
  degil). Ayarlar: **bicak payi/kerf · parca boslugu · kenar boslugu ·
  cozunurluk · rotasyon** — hepsi acikli (? Aciklama). Sonuc tabaka basi
  onizlenir (doluluk %), DXF + vektorel PDF olarak disari aktarilir.

**v1.5 yenilikleri:**
- **Vektorel onizleme:** web onizlemeleri artik flatten edilmis cizgi yerine
  **gercek egri komutlariyla** (SVG bezier `C`/`Q`) ciziliyor. DXF yaylari/
  spline'lari ve G-Code `G2/G3` yaylari **sonsuz yaklastirmada purüzsuz** kalir;
  cizgiler `non-scaling-stroke` ile her zoom'da ince/sabit. Yay = birkaç bezier
  (yuzlerce nokta yerine) -> daha kompakt veri + daha hafif DOM.
- Butunluk dogrulamasi CIRCLE->polyline donusumunun flatten OLCUM artefaktina
  (~5e-5) karsi sağlamlastirildi (sekil zaten birebir; cembersiz dosyalar hala
  tam-siki 1e-6 ile dogrulanir).

**v1.4 yenilikleri:**
- **Sol-ust hedef baslangic algoritmasi** (yukaridaki "1) Baslangic noktasi"):
  deterministik, karmasik/kucuk parcalarda kusursuz, elle-optimize yerlesimine
  en yakin. Arayuzde **destek yonu** secici (Sol-ust / Orta-ust / Sag-ust).
- **Node temizligi O(n)** yigin-tabanli algoritmaya gecti — 100.000+ node'lu
  buyuk nesting dosyalari saniyeler icinde islenir.

**v1.3 yenilikleri:**
- **Onizleme gecmisi:** her DXF isleme/nesting ve her G-Code siralama/duzenleme
  adimi tiklanabilir bir **gecmis seridine** yazilir; herhangi bir adima
  donebilirsiniz (geri/ileri + serit).
- **Tekerlekle yaklastirma:** onizleme panellerinde **fare tekerlegi** ile
  zoom, **surukleyerek** kaydirma, **cift tik** ile sifirlama.
- **Gezginde siralama:** varsayilan **Yeni → Eski** (degistirlebilir: Ad, Tur,
  Boyut, Eski→Yeni). **En son girilen klasor** farkli renkte (amber) vurgulanir.

- **Dosya gezgini (sol kenar):** klasorler arasinda gezin (ust yol cubugu /
  "Ev" / "Proje" kisayollari), DXF/G-Code dosyalarina tiklayarak acin.
  Elle yol yazmaya gerek yok.
- **Cok sekmeli calisma:** actiginiz her dosya ust tarafta **ayri bir sekme**
  olur; aralarinda gecis yapabilirsiniz. "Klasordeki tum DXF'leri ac" ile bir
  klasordeki tum DXF'ler tek tusla ayri sekmelerde acilir.
- **DXF sekmesi:** parametreleri (baslangic yatay/dikey, node toleransi, node
  temizligi ac/kapa) ayarla → **ONCESI/SONRASI** baslangic noktalarini **anlik**
  gor. "Yeniden Isle" onizler (diske yazmaz), "Optimize DXF'i Kaydet" yazar.
- **G-Code sekmesi:** numarali blok listesi + canli sira onizlemesi
  (numara = kesim sirasi, ok = tasima yolu).
  - **Elle siralama:** bloklari **surukle-birak** ile tasi, ya da `59 60` yazip
    iki blogun yerini degistir.
  - **Auto / Serpantin / Engel** ile otomatik sirala (hepsi icerme kuralini korur).
  - **↶ / ↷** (geri al / yinele), **Canli onizleme** toggle, **Goster**, **Kaydet**.
  - Icerme ihlalleri kirmizi vurgulanir ve raporlanir.
- **Toplu Isle (sag ust):** secili klasordeki her sey ayri dizinlere islenir.

---

## Proje / klasor modu

Her sey ayri dizinlere yerlesir, karisiklik olmaz:

```
<proje_kok>/<proje_adi>/
    01_girdi/            islenen girdilerin kopyasi
    02_dxf_optimized/    optimize DXF ciktilari
    03_gcode_reordered/  yeniden siralanmis G-Code
    04_onizleme/         PNG onizlemeler
    proje.json           ayarlar + islem gunlugu
```

```bash
# Klasordeki tum .dxf ve G-Code dosyalarini isim sirasiyla otomatik isle
python main.py /yol/klasor --proje musteriA --proje-kok /cikti/klasoru

# Tekil dosyalari da proje dizinlerine yazdirabilirsiniz
python main.py a.dxf b.tap --proje musteriA
```

Guvenlik onlemleri:
- **G91 (artimli mod)** tespit edilirse islem iptal edilir (siralamak konumlari
  bozardi).
- Program-sonu satirlari (M2/M30/M5/`%` ...) sona tasinir.
- Z geri cekme (retract) ile bitmeyen son blok **yerinde sabitlenir** (kesim
  derinliginde yatay hareketi onlemek icin).

Cikti `*_reordered.tap` olarak yazilir.

---

## Etkilesimli G-Code editoru (`-e`)

`python main.py kesim.tap -e` ile acilir. Numarali blok listesini gosterir ve
siralamayi canli olarak duzenlemenizi saglar:

```
Komutlar:
  <i> <j>         i ve j. siradaki bloklarin yerini degistir (orn: 59 60)
  tasi <i> <j>    i. bloku j. konuma tasi
  auto            varsayilan siralama (sol-alt -> sag-ust, destek korumali)
  engel           engel-farkindalikli (golge) siralama
  serp            serpantin (zigzag) siralama
  liste           blok listesini goster
  geri            son degisikligi geri al
  ileri           geri alinani yinele
  onizleme        canli PNG onizleme ac/kapa (toggle)
  goster          su anki sirayla PNG onizleme uret
  kaydet [dosya]  yeniden siralanmis .tap olarak yaz
  yardim          bu yardimi goster
  cik             cikis
```

- **Yer degistirme** (istediginiz ornek): terminale `59 60` yazarsaniz 59. ve
  60. siradaki bloklar yer degistirir.
- **Canli onizleme toggle:** `onizleme` komutu ile PNG onizlemesini acip
  kapatabilirsiniz. Aciksa **her degisiklikte** PNG (`*_sira_onizleme.png`)
  otomatik guncellenir; kapaliyken `goster` ile tek seferlik uretebilirsiniz.
  Basta acik baslatmak icin `--canli-onizleme`.
- **Geri alma:** `geri` / `ileri` ile sinirsiz adim geri alip yineleyebilirsiniz.

---

## Uretilen dosyalar

| Girdi | Cikti |
|---|---|
| `tabaka.dxf` | `tabaka_optimized.dxf` — optimize DXF |
| `tabaka.dxf` | `tabaka_oncesi_sonrasi.png` — ONCESI/SONRASI baslangic gorseli |
| `kesim.tap` | `kesim_reordered.tap` — yeniden siralanmis G-Code |
| `kesim.tap` (editor) | `kesim_sira_onizleme.png` — canli sira gorseli |

---

## Komut satiri secenekleri

```
Genel / arayuz:
  --web               Web arayuzunu baslat
  --port PORT         Web portu                                     (8000)
  --proje AD          Proje adi (ciktiler ayri dizinlere yerlesir)
  --proje-kok DIZIN   Proje kok dizini

DXF secenekleri:
  --alan-orani        Risk esigi: parca alani / tabaka alani         (0.10)
  --boyut-orani       Risk esigi: parca eni-boyu / tabaka eni-boyu   (0.50)
  --destek-yonu       Baslangic (kopma) hedef bolgesi: sol-ust|ust|sag-ust (sol-ust)
  --node-tol          Node sadelestirme toleransi                    (1e-06)
  --node-temizleme-yok  Gereksiz node temizligini kapat
  --onizleme-yok      DXF icin PNG uretme

G-Code secenekleri:
  --serpantin         Zigzag siralama
  --engel             Engel-farkindalikli siralama
  -e, --etkilesimli   Etkilesimli (canli) siralama editorunu ac
  --canli-onizleme    Editorde PNG onizlemeyi basta ACIK baslat
```

---

## Proje yapisi

```
Cnc-Assistant/
├── main.py                     # ince giris noktasi (geriye uyumluluk)
├── cnc_assistant/
│   ├── geometry.py             # node temizligi + baslangic hedefleme (saf python)
│   ├── dxf_processor.py        # DXF okuma/yazma, adim 1-2, butunluk dogrulama
│   ├── gcode.py                # G-Code ayristirma + icerme + siralama stratejileri
│   ├── preview.py              # oncesi/sonrasi + sira PNG onizlemeleri
│   ├── interactive.py          # etkilesimli terminal editoru (geri-al + onizleme)
│   ├── project.py              # proje dizin yapisi + klasor toplu isleme
│   ├── webapp.py               # bagimliliksiz web sunucusu (http.server)
│   ├── web/                    # arayuz (index.html + app.js)
│   └── cli.py                  # argparse komut satiri
├── tests/                      # birim testleri
├── examples/ornek_uret.py      # demo DXF/G-Code uretici
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Testler

```bash
# pytest ile
pytest

# veya bagimsiz calistirma
python tests/test_geometry.py
python tests/test_gcode.py
```

---

## Desteklenen varliklar / sinirlar

- **Optimize edilir:** kapali `LWPOLYLINE`, kapali 2D `POLYLINE`, `CIRCLE`.
- **Korunur (dokunulmaz):** parametrik kapali `SPLINE`/`ELLIPSE` — baslangic
  guvenle kaydirilamayacagindan oldugu gibi birakilir (konsola not dusulur).
- G-Code tarafinda **mutlak mod (G90)** beklenir; **G91** tespitinde islem
  guvenlik nedeniyle iptal edilir.

---

## Lisans

MIT — bkz. [LICENSE](LICENSE).
