# İnceleme etiketleme kılavuzu

Bu kılavuz `labeled_reviews*.jsonl` ve `claude_labeled_reviews.jsonl` dosyalarındaki olumsuz Steam incelemelerinin nasıl etiketlendiğini anlatır. İnsan da Claude da aynı kuralları kullanır.

## Temel kural

Bir kategoriyi, **inceleyen o şikayeti bu oyun hakkında açıkça dile getiriyorsa** işaretle.
- Bir inceleme birden çok kategori alabilir. Çoğu inceleme bir ya da iki kategori alır; bazıları hiç almaz.
- **Sadece yazılanı say:** ima, tahmin ya da "muhtemelen şunu kastetmiş" sayılmaz.
- **Kategori yoksa boş bırak:** küfür, genel öfke ("çöp oyun") ya da tek kelimelik inceleme hiçbir kategori almaz.

## Kategoriler

| Kod | Ad | Ne zaman işaretlenir | Ne zaman işaretlenmez |
|---|---|---|---|
| `controls` | Kötü kontroller / hantal his | Kontroller, kamera, direksiyon, hareket ya da fizik hantal, tepkisiz, garip ya da zor. Tuş atamasının olmaması, direksiyon/gamepad desteğinin kötü olması. | Arayüzün kafa karıştırması (`ui_ux`). Bir şeyin bozuk çalışması `bugs`'tır: tuş hiç tepki vermiyor, karakter takılıyor, kumanda desteği var deniyor ama hiç çalışmıyor, bir mekanik sürekli arıza çıkarıyor. |
| `bugs` | Oyunu bozan hatalar | Hatalar, çökme, donma, takılıp kalma, kaybolan kayıtlar, çalışmayan özellik, oyunun açılmaması, hatalar yüzünden oynanamaması. Saçma yapay zekâ davranışı (yürümeyen zombiler, kapıdan geçen karakterler, duvar ya da çalı arkasından vuran düşmanlar) da buraya girer. | "Bitmemiş" deniyor ama hata anlatılmıyorsa. "Hiç hata yok". |
| `ui_ux` | Kafa karıştıran arayüz / deneyim | Menüler ve ekranlar karışık, öğretici yok ya da kötü, oyun ne yapılacağını anlatmıyor, bilgi bulunamıyor. | Sıkıcı ya da tekrarlayan oynanış (`content`). |
| `content` | Az içerik / sığ ilerleme | Yapacak az şey var, oyun kısa, oynanış tekrarlıyor ya da sıkıcı, ilerleme sığ, temel bir özellik eksik ("sadece şu var, başka bir şey yok", "boş ve ıssız"). | Vaat edilip verilmeyen özellik (`abandoned`). Kötü oyun ya da bölüm tasarımı, oynanışın kötü hissettirmesi (kategori yok, ya da duruma göre `controls`). Sadece "bitmemiş" demesi (aşağıya bakın). |
| `performance` | Kötü performans / optimizasyon | Düşük FPS, takılma (stutter), uzun yükleme, kötü optimizasyon, oyunun güçlü bilgisayarda bile yavaş çalışması. | Online bağlantı ya da sunucu sorunları: lag, bağlantı kopması, sunucuya girilememesi (`bugs`). Çökme (`bugs`). |
| `abandoned` | Geliştirici bıraktı / güncelleme yok | Güncellemeler durdu, geliştirici oyunu bıraktı ya da oyuncuları umursamıyor. Vaatler ya da yol haritası tutulmadı, yıllardır erken erişimde/bitmemiş, "para tuzağı". Yıllardır güncellenmemesi ("6 yıldır güncelleme yok"). Sunucuların kapatılması, oyunun artık oynanamaması ("en azından çevrimdışı mod verin"). | Geliştiricinin kişisel görüşleri ya da tartışmaları. Sadece fiyat (`price`). |
| `realism` | Gerçekçi simülasyon değil | Oyunun simüle ettiği iş gerçekçi değil: arcade gibi, fiziği ya da ayrıntıları gerçek hayata uymuyor. Oyunu simülasyon olarak yetersiz bulan karşılaştırmalar da sayılır: "gerçek bir çiftlik simülasyonu istiyorsan şunu oyna", "çok daha iyi tiyatro simülatörleri var". | Hatalı fizik (`bugs`). Hantal his (`controls`). |
| `price` | Fiyatına değmez / parayla kazanma | Oyun fiyatına değmiyor ya da pahalı ("bu fiyata değmez", "indirimde alın", "overpriced"). Parayla kazanma (pay-to-win), oyun içi satın almalar, mikro ödemeler, para sızdıran DLC ya da sezon bileti düzeni. | "Para tuzağı" (cash grab) ve bitmemiş ya da bırakılmış oyun (`abandoned`). Sadece geri ödeme hikayesi ("iade ettim"). |
| `cheaters` | Hileciler / hackerlar | Çok oyunculu modda hileciler, hackerlar, aimbot ya da wallhack kullananlar; geliştiricinin onlara karşı bir şey yapmaması. | Anti-cheat yazılımının kendisinden şikayet (Linux'u engellemesi, çökertmesi: duruma göre `bugs` ya da kategori yok). Yapay zekânın "hile yapması" (`bugs` ya da kategori yok). Güvenlik açığı (`bugs`). |
| `scope_unrealistic` | AAA beklentisi | İnceleyen bir indie oyundan AAA ölçeği bekliyor: GTA ile kıyaslıyor, dev bir açık dünya ya da büyük bir stüdyonun içeriğini istiyor. | Oyunun kendi vaat ettiği şeyi vermemesi (`abandoned`). |

**`idea_praise`:** İnceleyen oyunu önermiyor ama oyunu, fikrini, konseptini ya da potansiyelini övüyor: "harika fikir ama...", "çok potansiyeli var", "çok sevmek istedim", "gerçekten çok iyi bir oyun ama geliştiricinin kararları mahvetti", "bu oyunu çok seviyorum ama...", "ilk hâli muhteşemdi". Tek bir özelliği övmek ("grafikler güzel", "müzik iyi") yetmez; oyunun bütününü ya da fikrini övmeli.

## Sınır kuralları

1. **"Bitmemiş":**
   - Tek başına `abandoned`'dır, yeter ki geliştiricinin bıraktığı, yıllardır bitmediği ya da güncellenmediği anlaşılsın.
   - Bunun yanında içeriğin azlığı açıkça söyleniyorsa ("yapacak şey yok", "boş", "içerik çok az") `content` de eklenir.
   - Bitmemiş olduğu hatalar üzerinden anlatılıyorsa `bugs` eklenir.
2. **Vaat edilen ama gelmeyen özellik** (mağaza sayfası, yol haritası, Kickstarter) `abandoned`'dır, `content` değil.
   - "Bait and switch" ve vaat edilen türü vermemek ("MMO değil", "open world dendi, değil") da `abandoned`'dır.
   - "Sahte reklam" (false advertising) ancak eksik olan şey söyleniyorsa `abandoned`'dır: "co-op diye satıldı, co-op yok". Sadece "false advertising" deniyorsa ya da grafiklerin fragmandakinden kötü olmasından söz ediliyorsa kategori almaz. Başka bir neden söylüyorsa ona göre etiketlenir (sıkıcı → `content`).
   - Kural Kasım 2026'da kullanıcının kararıyla eklendi.
3. **"Kötü tasarım", "eğlenceli değil", "oynanış berbat":** bunlar tek başına kategori almaz. İnceleyen nedenini söylüyorsa nedene göre etiketle: tekrarlıyor → `content`, kontroller kötü → `controls`.
4. **Geri ödeme hikayesi, başka oyunların daha iyi olması ve geliştiricinin tartışmaları** şikayet kategorisi değildir.
   - Fiyat Kasım 2026'ya kadar da kategori dışıydı; o zamandan beri `price`, hileciler de `cheaters`'tır (kullanıcının kararı). Bu kararla etiketlenen satırlarda `"schema": 2` vardır. Bu alanı olmayan eski satırlarda fiyat ve hile hiç işaretlenmedi, bu yüzden bu iki kategori yalnızca `schema` 2 satırlarda ölçülür.
5. **Olumsuzlanmış ifadeler sayılmaz:** "hiç hata yok", "performans iyi".
6. **Eski ve yeni durum:** "eskiden çok çöküyordu ama düzeldi" artık bir şikayet değil, kategori yok. Hâlâ geçerliyse say.
7. **Emin değilsen işaretleme.** İnsan etiketlemesinde "emin değilim" seçeneği o incelemeyi ölçümden çıkarır.
