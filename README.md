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

### 1) Baslangic noktasi optimizasyonu (DXF)

Kapali her vektor icin baslangic noktasi, parca tipine gore secilir:

| Parca tipi | Baslangic hedefi | Neden |
|---|---|---|
| **Normal parca** | Ust kenarda, **orta-ust ile sag-ust arasinda** (kose degil!) | Kose noktasi yerine iceride bir nokta secilir ki kesim sonuna kadar **destek korunur**. Varsayilan konum `--bas-x-orani 0.75`. |
| **Uzun-ince serit** (orn. dikey "I", ince cubuk) | **Sag kenarda**, dikeyde ortada | Serit kesilirken her iki uctan da destekte kalir. `--serit-y-orani 0.5`. |
| **Cember** | Sag-ust 45° | CIRCLE baslangic tasimaz; es-geometrik 2-yayli polyline'a cevrilip baslangic verilir (form/olcu birebir ayni). |

**Hedef bolgede uygun bir vertex yoksa**, programcik en yakin **duz** segment
uzerine — geometriyi bozmadan — yeni bir nokta ekler ve baslangici oraya tasir
(el yazisi gibi serbest egriler icin). Eklenen nokta var olan segmenti yalnizca
ikiye boler; sekil/uzunluk degismez.

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

Uc sekme:

- **DXF:** dosya sec, parametreleri (baslangic yatay/dikey, node toleransi,
  node temizligi ac/kapa) ayarla, **ONCESI/SONRASI** baslangic noktalarini
  **anlik** SVG olarak gor. "Onizle + Kaydet" optimize DXF'i yazar.
- **G-Code:** dosya yukle; numarali blok listesi + canli sira onizlemesi
  (numara = kesim sirasi, ok = tasima yolu) gelir.
  - **Elle siralama:** bloklari **surukle-birak** ile tasi, ya da `59 60`
    yazip iki blogun yerini degistir.
  - **Auto / Serpantin / Engel** butonlari ile otomatik sirala (hepsi icerme
    kuralini korur).
  - **Geri / Ileri** (undo/redo), **Canli onizleme** toggle'i (her degisiklikte
    guncelle ac/kapa), **Goster** (tek seferlik), **Kaydet**.
  - Icerme ihlalleri kirmizi vurgulanir ve alt bilgide raporlanir.
- **Proje / Klasor:** bir klasor + proje adi ver, "Klasoru Otomatik Isle" ile
  icindeki her sey ayri dizinlere islenir.

Arayuz saf HTML/JS'tir (SVG ile cizim); onizlemeler **anlik** ve tarayici
tarafinda uretilir.

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
  --bas-x-orani       Normal parca baslangic yatay konumu            (0.75)
                      (0.5=orta-ust, 1.0=sag-ust)
  --serit-y-orani     Serit parca sag-kenar dikey konumu             (0.50)
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
