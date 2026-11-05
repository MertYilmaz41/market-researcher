"""Turkish interface text: English template -> Turkish template (see i18n.py).

Placeholders must match the English ones (tests/test_i18n.py checks it). Number formats like
{n:,} and {s:.0%} are rendered the Turkish way (1.460, %73), so templates keep them as they are;
where the English writes "{x:.0f}%", Turkish writes "%{x:.0f}".
Terms: review = inceleme, % positive = % olumlu, demand = talep, tag = etiket,
underserved = karşılanmamış, well served = iyi karşılanmış, score = puan.
"""

TR: dict[str, str] = {
    # ---- notices: before a run
    "Demand not proven": "Talep kanıtlanmadı",
    "Games with fewer than {n} reviews don't prove that players want the idea.":
        "{n} incelemeden az olan oyunlar, oyuncuların bu fikri istediğini kanıtlamaz.",
    "The method recommends at least {n} reviews, ideally {ideal}+.":
        "Yöntem en az {n}, ideal olarak {ideal}+ inceleme önerir.",
    "Above 70% isn't underserved": "%70 üstü karşılanmamış sayılmaz",
    "Games above {max:g}% positive satisfied their players, so they score 0.":
        "%{max:g} üstü olumlu oyunlar oyuncularını memnun etmiş, bu yüzden 0 puan alırlar.",
    "Keep '% positive to' at {max:g} or lower to focus on disappointed audiences.":
        "Hayal kırıklığına uğramış kitlelere odaklanmak için '% olumlu (en çok)' değerini {max:g} veya altında tutun.",
    "Very low ratings included": "Çok düşük puanlar dahil",
    "Ratings under {min:g}% are often troll-bombed or broken listings.":
        "%{min:g} altındaki puanlar çoğu zaman trol saldırısı ya da bozuk mağaza sayfalarıdır.",
    "The method starts at {min:g}%.": "Yöntem %{min:g}'ten başlar.",
    "This may take a while": "Bu biraz sürebilir",
    "The first run of a tag with these settings can take about {min} min "
    "because Steam and SteamSpy limit request speed.":
        "Bu ayarlarla bir etiketin ilk taraması yaklaşık {min} dk sürebilir, "
        "çünkü Steam ve SteamSpy istek hızını sınırlıyor.",
    "Later runs of the same tag load from the cache in seconds.":
        "Aynı etiketin sonraki taramaları önbellekten saniyeler içinde yüklenir.",

    # ---- notices: after a tag run
    "No game has all these tags": "Bu etiketlerin hepsine sahip oyun yok",
    "No game on SteamSpy is tagged {tag}.": "SteamSpy'da {tag} etiketli oyun yok.",
    "Remove a tag or pick a broader one.": "Bir etiketi kaldırın ya da daha geniş bir etiket seçin.",
    "Very broad tag": "Çok geniş etiket",
    "'{tag}' has {n:,} games. The method works best on specific genres with a clear player fantasy.":
        "'{tag}' etiketinde {n:,} oyun var. Yöntem, net bir oyuncu fantezisi olan belirli türlerde en iyi çalışır.",
    "Try a narrower tag, e.g. {examples}.": "Daha dar bir etiket deneyin, örneğin {examples}.",
    "Audience already well served": "Kitle zaten iyi karşılanıyor",
    "Only {under:,} of the {rated:,} rated games with demand are underserved; {well:,} are {good}%+ positive.":
        "Talep gören {rated:,} oyundan yalnızca {under:,} tanesi karşılanmamış; {well:,} tanesi %{good}+ olumlu.",
    "Players here already have good games. Compare tags in the Markets view (sr markets).":
        "Buradaki oyuncuların zaten iyi oyunları var. Etiketleri Pazarlar görünümünde karşılaştırın (sr markets).",
    "No games with enough reviews": "Yeterli incelemesi olan oyun yok",
    "None of the {n:,} games tagged '{tag}' has {min:,}+ reviews.":
        "'{tag}' etiketli {n:,} oyunun hiçbirinde {min:,}+ inceleme yok.",
    "Lower 'Minimum reviews' in Filters, or try a more popular tag.":
        "Filtrelerde 'En az inceleme' değerini düşürün ya da daha popüler bir etiket deneyin.",
    "No games in the rating range": "Puan aralığında oyun yok",
    "{n:,} games have {min:,}+ reviews, but none is {lo:g}-{hi:g}% positive. Players seem happy with this genre.":
        "{n:,} oyunun {min:,}+ incelemesi var ama hiçbiri %{lo:g}-{hi:g} olumlu değil. "
        "Oyuncular bu türden memnun görünüyor.",
    "Widen the '% positive' range in Filters, or try another tag.":
        "Filtrelerde '% olumlu' aralığını genişletin ya da başka bir etiket deneyin.",
    "Nothing left to rank": "Sıralanacak oyun kalmadı",
    "Every candidate turned out to be DLC, a soundtrack or failed to load.":
        "Adayların hepsi DLC ya da film müziği çıktı veya yüklenemedi.",
    "Try another tag or wider filters.": "Başka bir etiket ya da daha geniş filtreler deneyin.",
    "Few candidates": "Az aday",
    "Only {n} game(s) passed the filters.": "Filtrelerden yalnızca {n} oyun geçti.",
    "Try a related tag or a wider '% positive' range for more to compare.":
        "Karşılaştıracak daha çok oyun için ilgili bir etiket ya da daha geniş bir '% olumlu' aralığı deneyin.",
    "Not every candidate analyzed": "Her aday analiz edilmedi",
    "Analyzed the top {n} of {total} candidates (by review count).":
        "{total} adaydan inceleme sayısına göre ilk {n} tanesi analiz edildi.",
    "Raise 'Games to analyze' in Filters to include more.":
        "Daha fazlasını dahil etmek için Filtrelerde 'Analiz edilecek oyun' değerini artırın.",
    " and {n} more": " ve {n} tane daha",
    "{n} game(s) couldn't be analyzed": "{n} oyun analiz edilemedi",
    "Skipped: {names}{more}. Reason: {reason}": "Atlananlar: {names}{more}. Sebep: {reason}",
    "Run again later; games that loaded are cached.": "Daha sonra tekrar çalıştırın; yüklenen oyunlar önbellekte.",
    "{name} ({rating:.0f}%)": "{name} (%{rating:.0f})",
    "Steam rates some games differently": "Steam bazı oyunları farklı puanlıyor",
    "SteamSpy put {n} game(s) in {lo:g}-{hi:g}% positive, but Steam's own numbers don't: {names}. "
    "They stay in the ranking, scored on Steam's numbers.":
        "SteamSpy {n} oyunu %{lo:g}-{hi:g} olumlu aralığına koydu ama Steam'in kendi rakamları koymuyor: {names}. "
        "Bu oyunlar sıralamada kalır ve Steam'in rakamlarıyla puanlanır.",
    "Review texts unavailable": "İnceleme metinleri alınamadı",
    "Couldn't load review texts for {n} game(s), so their complaints weren't mined and fixability "
    "was assumed to be 50%.":
        "{n} oyunun inceleme metinleri yüklenemedi; bu yüzden şikayetleri çıkarılamadı ve "
        "düzeltilebilirlik %50 varsayıldı.",
    "Run again later to fill them in.": "Eksikleri doldurmak için daha sonra tekrar çalıştırın.",
    "No real opportunity found": "Gerçek bir fırsat bulunamadı",
    "Every analyzed game is above 70% positive once review bombs are removed, so none shows a disappointed audience.":
        "İnceleme bombardımanları çıkarıldığında analiz edilen her oyun %70'in üstünde olumlu; "
        "hiçbiri hayal kırıklığına uğramış bir kitle göstermiyor.",
    "Try another tag, e.g. {examples}.": "Başka bir etiket deneyin, örneğin {examples}.",
    "Only weak opportunities": "Yalnızca zayıf fırsatlar",
    "The best score is {score:.0f}/100.": "En iyi puan {score:.0f}/100.",
    "Compare with another tag before committing to this genre.":
        "Bu türe karar vermeden önce başka bir etiketle karşılaştırın.",
    "Analysis complete": "Analiz tamamlandı",
    "Ranked {n} game(s). Top opportunity: {name} (score {score:.0f}).":
        "{n} oyun sıralandı. En iyi fırsat: {name} (puan {score:.0f}).",
    "Click a game on the map or in the table for details.":
        "Ayrıntılar için haritada ya da tabloda bir oyuna tıklayın.",

    # ---- notices: single game
    "Not a game": "Oyun değil",
    "AppID {appid} is a {kind}, not a game, so this analysis doesn't apply.":
        "AppID {appid} bir oyun değil ({kind}), bu yüzden bu analiz geçerli değil.",
    "Use the base game's AppID from its Steam store page.":
        "Ana oyunun Steam mağaza sayfasındaki AppID'yi kullanın.",
    "No store page": "Mağaza sayfası yok",
    "This game is delisted or region-locked, so price and category data are missing.":
        "Bu oyun mağazadan kaldırılmış ya da bölgeye kilitli, bu yüzden fiyat ve kategori bilgisi yok.",
    "Its audience may be orphaned; check the game manually.":
        "Kitlesi sahipsiz kalmış olabilir; oyunu elle kontrol edin.",
    "Only {n:,} reviews; the method needs {min}+ to show real demand.":
        "Yalnızca {n:,} inceleme var; yöntem gerçek talebi göstermek için {min}+ inceleme ister.",
    "Treat the score as unreliable.": "Puanı güvenilmez kabul edin.",
    "{rating:.0f}% positive overall, but {adjusted:.0f}% once review bombs are removed":
        "genel olarak %{rating:.0f} olumlu, ama inceleme bombardımanları çıkarılınca %{adjusted:.0f}",
    "{rating:.0f}% positive": "%{rating:.0f} olumlu",
    "Players are satisfied": "Oyuncular memnun",
    "This game is {detail}, so it isn't an underserved audience (score 0).":
        "Bu oyun {detail}; yani karşılanmamış bir kitle değil (puan 0).",
    "Look for games under 70% positive.": "%70'in altında olumlu olan oyunlara bakın.",
    "Free game": "Ücretsiz oyun",
    "It's free to play, so the Box Method revenue estimate doesn't apply.":
        "Oyun ücretsiz, bu yüzden Box Method gelir tahmini uygulanmaz.",
    "Complaints couldn't be mined; fixability was assumed to be 50%.":
        "Şikayetler çıkarılamadı; düzeltilebilirlik %50 varsayıldı.",
    "Try again later.": "Daha sonra tekrar deneyin.",
    "No negative reviews to mine": "İncelenecek olumsuz inceleme yok",
    "There are no English negative reviews, so there are no complaints to learn from.":
        "İngilizce olumsuz inceleme yok, bu yüzden öğrenilecek şikayet de yok.",

    # ---- errors
    "the data service": "veri servisi",
    "{host} timed out": "{host} zaman aşımına uğradı",
    "{host} didn't answer in time.": "{host} zamanında yanıt vermedi.",
    "Check your internet connection and try again.": "İnternet bağlantınızı kontrol edip tekrar deneyin.",
    "Can't reach {host}": "{host} adresine ulaşılamıyor",
    "The connection to {host} failed.": "{host} bağlantısı kurulamadı.",
    "{host} is busy": "{host} meşgul",
    "{host} is rate-limiting or temporarily down ({error}).":
        "{host} istekleri sınırlıyor ya da geçici olarak kapalı ({error}).",
    "Wait a minute and try again. Data already downloaded is kept in the cache.":
        "Bir dakika bekleyip tekrar deneyin. İndirilmiş veriler önbellekte kalır.",
    "{host} refused the request": "{host} isteği reddetti",
    "{host} answered HTTP {status}.": "{host} HTTP {status} ile yanıt verdi.",
    "Try again later. If it keeps happening, the service may have changed.":
        "Daha sonra tekrar deneyin. Devam ederse servis değişmiş olabilir.",
    "Unexpected answer from {host}": "{host} beklenmedik bir yanıt verdi",
    "{host} returned something other than the expected data. The service may have changed.":
        "{host} beklenen veriden farklı bir şey döndürdü. Servis değişmiş olabilir.",
    "Try again later. If it persists, the data source needs an update.":
        "Daha sonra tekrar deneyin. Sürerse veri kaynağının güncellenmesi gerekir.",
    "Unexpected error": "Beklenmedik hata",
    "Try again. If it keeps happening, run the CLI with SR_DEBUG=1 for details.":
        "Tekrar deneyin. Devam ederse ayrıntılar için CLI'ı SR_DEBUG=1 ile çalıştırın.",
    "Tag can't be searched": "Etiket aranamıyor",
    "'{tag}' is a Steam tag, but SteamSpy (the data source) can't search it.":
        "'{tag}' bir Steam etiketi, ama veri kaynağı SteamSpy bu etiketi arayamıyor.",
    "Pick a related tag instead, e.g. {examples}.": "Bunun yerine ilgili bir etiket seçin, örneğin {examples}.",
    " or ": " ya da ",
    "Did you mean {names}?": "Şunu mu demek istediniz: {names}?",
    "Check the spelling. Examples: {examples}.": "Yazımı kontrol edin. Örnekler: {examples}.",
    "Tag not found": "Etiket bulunamadı",
    "SteamSpy has no games tagged '{tag}'.": "SteamSpy'da '{tag}' etiketli oyun yok.",

    # ---- risk flags
    "{period}: {n:,} reviews ({share:.0%} of all), {neg:.0%} negative. "
    "Likely a review bomb or controversy, not poor execution.":
        "{period}: {n:,} inceleme (tümünün {share:.0%} kadarı), {neg:.0%} olumsuz. "
        "Muhtemelen kötü yapımdan değil, bir inceleme bombardımanı ya da tartışmadan.",
    "{period}: {n:,} reviews ({share:.0%} of all) in one period. Check whether a streamer/viral moment drove demand.":
        "{period}: tek dönemde {n:,} inceleme (tümünün {share:.0%} kadarı). "
        "Talebi bir yayıncının ya da viral bir anın getirip getirmediğine bakın.",
    "Excluding spike periods: {n:,} reviews, {rating:.0f}% positive.":
        "Sıçrama dönemleri hariç: {n:,} inceleme, %{rating:.0f} olumlu.",
    "Rated {lately:.0f}% positive in the last 12 months vs {overall:.0f}% all time "
    "({n:,} recent reviews): the problems may already be fixed.":
        "Son 12 ayda %{lately:.0f} olumlu, tüm zamanlarda %{overall:.0f} ({n:,} yeni inceleme): "
        "sorunlar çoktan düzeltilmiş olabilir.",
    "Only {share:.1%} of its reviews ({n:,}) came in the last 12 months. The audience may have moved on.":
        "İncelemelerinin yalnızca {share:.1%} kadarı ({n:,}) son 12 ayda geldi. Kitle başka oyunlara geçmiş olabilir.",
    "Currently {discount}% off. Review counts may be inflated by deep sales.":
        "Şu an %{discount} indirimde. Büyük indirimler inceleme sayılarını şişirmiş olabilir.",
    "Sells for ${price:.2f}. Low price inflates units and reviews.":
        "${price:.2f} fiyatla satılıyor. Düşük fiyat satış ve inceleme sayısını şişirir.",
    "Online multiplayer ({modes}): needs netcode, hard for small teams.":
        "Çevrim içi çok oyunculu ({modes}): ağ kodu gerektirir, küçük ekipler için zor.",
    "Tags {tags}: technically demanding to do well.": "{tags} etiketleri: iyi yapmak teknik açıdan zor.",
    "Tags {tags}: niche audience, harder to reach and market to.":
        "{tags} etiketleri: niş kitle, ulaşması ve pazarlaması daha zor.",
    "No store data (delisted or region-locked). The audience may be orphaned; verify manually.":
        "Mağaza verisi yok (kaldırılmış ya da bölgeye kilitli). Kitle sahipsiz kalmış olabilir; elle doğrulayın.",
    "Store type is '{type}', not a game.": "Mağaza türü '{type}', oyun değil.",
    "{share:.0%} of negative reviews compare it to AAA games (GTA etc.). "
    "Part of the disappointment is scope an indie can't deliver.":
        "Olumsuz incelemelerin {share:.0%} kadarı oyunu AAA oyunlarla (GTA vb.) karşılaştırıyor. "
        "Hayal kırıklığının bir kısmı bağımsız bir ekibin karşılayamayacağı bir kapsamdan.",

    # ---- risk labels (config.RISK_LABELS)
    "Review bomb": "İnceleme bombardımanı",
    "Rating without spikes": "Sıçramasız puan",
    "Streamer spike": "Yayıncı sıçraması",
    "Deep discount": "Büyük indirim",
    "Very cheap": "Çok ucuz",
    "Online multiplayer": "Çevrim içi çok oyunculu",
    "Niche audience": "Niş kitle",
    "AAA expectations": "AAA beklentisi",
    "Hard tech": "Zor teknoloji",
    "Fading demand": "Azalan talep",
    "Already improved": "Zaten iyileşmiş",

    # ---- score card (scoring.explain)
    "Demand": "Talep",
    "Dissatisfaction": "Memnuniyetsizlik",
    "Fixability": "Düzeltilebilirlik",
    " ({adjusted:.0f}% with review-bomb periods removed)": " (inceleme bombardımanı dönemleri çıkarılınca %{adjusted:.0f})",
    "{n:,} reviews. Log scale: {lo} reviews = 0%, {hi:,}+ = 100%.":
        "{n:,} inceleme. Logaritmik ölçek: {lo} inceleme = %0, {hi:,}+ = %100.",
    "{rating}. {max:g}%+ positive = 0%, {min:g}% = 100%.": "{rating}. %{max:g}+ olumlu = %0, %{min:g} = %100.",
    "{fix:.0%} of complaint mentions are things a small team can fix (bugs, UI, performance...), not scope or genre.":
        "Şikayetlerin {fix:.0%} kadarı küçük bir ekibin düzeltebileceği şeyler (hatalar, arayüz, performans...), "
        "kapsam ya da tür değil.",
    "Reviews couldn't be mined, so {fix:.0%} is assumed.": "İncelemeler çıkarılamadı, bu yüzden {fix:.0%} varsayıldı.",

    # ---- review numbers and recent demand (report.py)
    "Steam's own numbers": "Steam'in kendi rakamları",
    "Steam's review histogram": "Steam inceleme grafiği",
    "SteamSpy estimate": "SteamSpy tahmini",
    " (SteamSpy says {rating:.0f}%)": " (SteamSpy'a göre %{rating:.0f})",
    "; {n:,} reviews from review-bomb periods count toward demand, not % positive":
        "; inceleme bombardımanı dönemlerinden {n:,} inceleme talebe sayılır, % olumluya sayılmaz",
    "{n:,} ({share:.0%})": "{n:,} ({share:.0%})",
    ", {rating:.0f}% positive": ", %{rating:.0f} olumlu",
    "{games:,} games, {demand:,} with demand, {under:,} underserved, {well:,} well served "
    "(gap {gap:.0%}), {gross} underserved gross":
        "{games:,} oyun, {demand:,} talep gören, {under:,} karşılanmamış, {well:,} iyi karşılanmış "
        "(boşluk {gap:.0%}), karşılanmamışların brüt geliri {gross}",

    # ---- complaints (mining/lexicon.py) and trends
    "Bad controls / clunky feel": "Kötü kontroller / hantal his",
    "Satisfying, tactile interactions": "Tatmin edici, dokunsal etkileşimler",
    "Game-breaking bugs": "Oyunu bozan hatalar",
    "Flawless execution and polish": "Kusursuz yapım ve cila",
    "Confusing UI / UX": "Kafa karıştırıcı arayüz / kullanım",
    "Seamless, intuitive UX as a selling point": "Satış noktası olarak akıcı, sezgisel kullanım",
    "Too little content / shallow progression": "Az içerik / sığ ilerleme",
    "Deep, early progression systems": "Erkenden başlayan derin ilerleme sistemleri",
    "Poor performance / optimization": "Kötü performans / optimizasyon",
    "Smooth performance on modest hardware": "Mütevazı donanımda akıcı performans",
    "Abandoned by developers / no updates": "Geliştiriciler bırakmış / güncelleme yok",
    "Ship complete, then keep updating and talking to players":
        "Eksiksiz çıkar, sonra güncellemeye ve oyuncularla konuşmaya devam et",
    "Not a real simulation / unrealistic": "Gerçek simülasyon değil / gerçekçi değil",
    "Authentic simulation depth in the core activity": "Ana etkinlikte gerçekçi simülasyon derinliği",
    "Players expect AAA-scale scope": "Oyuncular AAA ölçeğinde kapsam bekliyor",
    "Out of indie scope: don't chase it, position the game honestly":
        "Bağımsız ekip kapsamının dışında: peşinden koşma, oyunu dürüstçe konumlandır",
    "still common lately": "son zamanlarda hâlâ yaygın",
    "less common lately": "son zamanlarda daha az",
    "rarely mentioned lately": "son zamanlarda nadiren anılıyor",

    # ---- progress (pipeline)
    "Starting...": "Başlıyor...",
    "Listing games tagged {tag} from the Steam store": "Steam mağazasından {tag} etiketli oyunlar listeleniyor",
    "Checking store type: {name}": "Mağaza türü kontrol ediliyor: {name}",
    "Analyzing games": "Oyunlar analiz ediliyor",
    "Analyzed {name}": "Analiz edildi: {name}",
    "Reading tag {tag}": "Etiket okunuyor: {tag}",
    "Cancelled": "İptal edildi",

    # ---- web server
    "Steam tags": "Steam etiketleri",
    "Minimum reviews": "En az inceleme",
    "% positive from": "% olumlu (en az)",
    "% positive to": "% olumlu (en çok)",
    "Games to analyze": "Analiz edilecek oyun",
    "Reviews mined per game": "Oyun başına incelenen inceleme",
    "'% positive from' must not be higher than '% positive to'":
        "'% olumlu (en az)', '% olumlu (en çok)' değerinden büyük olamaz",
    "Check the filters": "Filtreleri kontrol edin",
    "Fix the highlighted values and try again.": "İşaretli değerleri düzeltip tekrar deneyin.",
    "AppID must be a positive number.": "AppID pozitif bir sayı olmalı.",
    "Game not found": "Oyun bulunamadı",
    "SteamSpy has no data for AppID {appid}.": "SteamSpy'da AppID {appid} için veri yok.",
    "Check the number on the game's Steam store page (store.steampowered.com/app/<AppID>/). "
    "Unreleased or very new games may not be listed yet.":
        "Numarayı oyunun Steam mağaza sayfasından kontrol edin (store.steampowered.com/app/<AppID>/). "
        "Çıkmamış ya da çok yeni oyunlar henüz listelenmemiş olabilir.",
    "This run no longer exists. It may have been deleted, or the server was restarted while it was running.":
        "Bu tarama artık yok. Silinmiş olabilir ya da çalışırken sunucu yeniden başlatılmış olabilir.",
    "This run doesn't exist.": "Böyle bir tarama yok.",
    "The run hasn't finished yet.": "Tarama henüz bitmedi.",
}
