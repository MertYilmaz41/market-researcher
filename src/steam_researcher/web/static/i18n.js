// Interface language of the page: English (default) or Turkish. Like i18n.py, text is written in
// English and looked up in TR; a missing entry shows the English. Text from the server (notices, the
// score card, complaint names, risk messages) already comes translated: every request sends X-Lang.
// One entry per line, "English": "Türkçe". tests/test_i18n.py reads this file and checks that every
// literal passed to t() and every data-i18n text in index.html has an entry with the same {placeholders},
// so always call t() with a literal, not a variable.
const TR = {
  // top bar, tag picker, filters
  "Proven demand + poor execution = high opportunity": "Kanıtlanmış talep + kötü yapım = büyük fırsat",
  "Steam tags": "Steam etiketleri",
  "Show all tags": "Tüm etiketleri göster",
  "Clear": "Temizle",
  "Filters": "Filtreler",
  "Find opportunities": "Fırsatları bul",
  "Searching...": "Aranıyor...",
  "Minimum reviews": "En az inceleme",
  "% positive from": "% olumlu (en az)",
  "% positive to": "% olumlu (en çok)",
  "Games to analyze": "Analiz edilecek oyun",
  "Reviews mined per game": "Oyun başına incelenen inceleme",
  "AppID or Steam URL": "AppID ya da Steam linki",
  "AppID or Steam store URL": "AppID ya da Steam mağaza linki",
  "Analyze": "Analiz et",
  "Analyzing...": "Analiz ediliyor...",
  "Language": "Dil",
  "Pick Steam tags...": "Steam etiketlerini seçin...",
  "Filter tags...": "Etiketleri süzün...",
  "Remove {tag}": "{tag} etiketini kaldır",
  "{n} selected (the maximum)": "{n} seçildi (en fazla)",
  "{n} selected · games must have all of them": "{n} seçildi · oyunlarda hepsi olmalı",
  "Tick one or more tags": "Bir ya da daha fazla etiket işaretleyin",
  "Selected": "Seçilenler",
  "All tags": "Tüm etiketler",
  "No Steam tag contains \"{query}\"": "\"{query}\" içeren Steam etiketi yok",
  "Steam tags, comma-separated, e.g. Crafting, Survival": "Steam etiketleri, virgülle ayrılmış, örn. Crafting, Survival",
  "Tag list unavailable": "Etiket listesi alınamadı",
  "The list of Steam tags couldn't be loaded.": "Steam etiketlerinin listesi yüklenemedi.",
  "You can still type tags by hand, separated by commas, e.g. Crafting, Survival.": "Etiketleri yine de elle, virgülle ayırarak yazabilirsiniz, örn. Crafting, Survival.",

  // validation and errors
  "This field": "Bu alan",
  "Check \"{field}\"": "\"{field}\" alanını kontrol edin",
  "This field can't be empty.": "Bu alan boş olamaz.",
  "Enter a number.": "Bir sayı girin.",
  "Enter a number from {min} to {max}.": "{min} ile {max} arasında bir sayı girin.",
  "Enter a number of at least {min}.": "En az {min} olan bir sayı girin.",
  "Use a multiple of {step}, e.g. {example}.": "{step} sayısının bir katını kullanın, örn. {example}.",
  "Pick at least one tag.": "En az bir etiket seçin.",
  "Tick one or more tags in the list.": "Listeden bir ya da daha fazla etiket işaretleyin.",
  "Type tags separated by commas, e.g. Crafting, Survival.": "Etiketleri virgülle ayırarak yazın, örn. Crafting, Survival.",
  "Use at most {n} tags.": "En fazla {n} etiket kullanın.",
  "Games must have every tag, so a few tags is usually enough.": "Oyunlarda her etiket olmalı, bu yüzden birkaç etiket genelde yeterli.",
  "'% positive from' ({lo}) is higher than '% positive to' ({hi}).": "'% olumlu (en az)' ({lo}), '% olumlu (en çok)' ({hi}) değerinden büyük.",
  "Swap the two values, e.g. 5 to 70.": "İki değerin yerini değiştirin, örn. 5 ile 70.",
  "Enter a Steam AppID or store link.": "Bir Steam AppID'si ya da mağaza linki girin.",
  "For example 1330660 or https://store.steampowered.com/app/1330660/": "Örneğin 1330660 ya da https://store.steampowered.com/app/1330660/",
  "\"{text}\" isn't an AppID or a Steam store link.": "\"{text}\" bir AppID ya da Steam mağaza linki değil.",
  "Use the number from the store URL, e.g. 1330660 from store.steampowered.com/app/1330660/": "Mağaza linkindeki sayıyı kullanın, örn. store.steampowered.com/app/1330660/ için 1330660",
  "Something went wrong": "Bir şeyler ters gitti",
  "Can't reach the Steam Researcher server": "Steam Researcher sunucusuna ulaşılamıyor",
  "The page lost its connection to the local server.": "Sayfanın yerel sunucuyla bağlantısı koptu.",
  "Is the Steam Researcher window still open? Start it again with Steam Researcher.bat, then reload this page.": "Steam Researcher penceresi hâlâ açık mı? Steam Researcher.bat ile yeniden başlatın, sonra bu sayfayı yenileyin.",
  "Request failed (HTTP {status})": "İstek başarısız oldu (HTTP {status})",
  "Dismiss": "Kapat",
  "Please wait": "Lütfen bekleyin",
  "Wait for it to finish, then try again.": "Bitmesini bekleyip tekrar deneyin.",
  "A search is still running.": "Bir arama hâlâ sürüyor.",
  "The analysis of the previous game is still running.": "Önceki oyunun analizi hâlâ sürüyor.",
  "The market ranking is still running.": "Pazar sıralaması hâlâ sürüyor.",

  // search progress
  "Fetching games tagged {tag}...": "{tag} etiketli oyunlar alınıyor...",
  "Searching \"{tag}\"...": "\"{tag}\" aranıyor...",
  "Cancel": "İptal",
  "Cancelling...": "İptal ediliyor...",
  "Stopping after the current step...": "Şu anki adımdan sonra duruyor...",
  "Search cancelled": "Arama iptal edildi",
  "The previous results are still shown.": "Önceki sonuçlar gösterilmeye devam ediyor.",
  "Search failed": "Arama başarısız oldu",
  "The search was interrupted": "Arama yarıda kesildi",
  "The server was restarted, so this run was lost.": "Sunucu yeniden başlatıldı, bu yüzden bu tarama kayboldu.",
  "Press Find opportunities again.": "Tekrar Fırsatları bul'a basın.",
  "Analyzing AppID {appid}...": "AppID {appid} analiz ediliyor...",
  "The first time can take ~15 s, longer if Steam's review server is slow.": "İlk sefer ~15 sn sürebilir; Steam'in inceleme sunucusu yavaşsa daha uzun.",
  "Shown in the details panel": "Ayrıntılar panelinde gösteriliyor",
  "{name} isn't part of the current ranking.": "{name} şu anki sıralamada yok.",
  "Analysis failed": "Analiz başarısız oldu",

  // map
  "Opportunity map": "Fırsat haritası",
  "Opportunity map, 2D": "Fırsat haritası, 2B",
  "Map view": "Harita görünümü",
  "Tick one or more tags and press Find opportunities.": "Bir ya da daha fazla etiket işaretleyip Fırsatları bul'a basın.",
  "Each bubble is a game; click one to inspect it. In 3D, drag to orbit and scroll to zoom.": "Her baloncuk bir oyun; incelemek için birine tıklayın. 3B'de döndürmek için sürükleyin, yakınlaştırmak için kaydırın.",
  "3D map unavailable": "3B harita kullanılamıyor",
  "3D map unavailable in this browser": "3B harita bu tarayıcıda kullanılamıyor",
  "The 3D library couldn't load (no internet, the CDN is blocked, or WebGL is off).": "3B kütüphanesi yüklenemedi (internet yok, CDN engelli ya da WebGL kapalı).",
  "The 2D map shows the same games. Reload the page to try 3D again.": "2B harita aynı oyunları gösterir. 3B'yi tekrar denemek için sayfayı yenileyin.",
  "x: demand · y: dissatisfaction · size: revenue · color: score · hover for fixability": "x: talep · y: memnuniyetsizlik · boyut: gelir · renk: puan · düzeltilebilirlik için üzerine gelin",
  "x: demand · y: dissatisfaction · z: fixability · size: revenue · color: score": "x: talep · y: memnuniyetsizlik · z: düzeltilebilirlik · boyut: gelir · renk: puan",
  "Score {score} · {n} reviews · {pct} pos": "Puan {score} · {n} inceleme · {pct} olumlu",
  "demand {demand} · dissatisfaction {dissatisfaction} · fixability {fixability}": "talep {demand} · memnuniyetsizlik {dissatisfaction} · düzeltilebilirlik {fixability}",
  " · -{points} risks": " · -{points} risk",
  "Demand →": "Talep →",
  "Dissatisfaction →": "Memnuniyetsizlik →",
  "Dissatisfaction ↑": "Memnuniyetsizlik ↑",
  "Fixability →": "Düzeltilebilirlik →",
  "Best opportunities ↗": "En iyi fırsatlar ↗",

  // ranking table
  "Ranking": "Sıralama",
  "{tag}: opportunity ranking": "{tag}: fırsat sıralaması",
  "{candidates} of {total} games have ≥ {min} reviews and {range} positive; analyzed the {n} with most reviews.": "{total} oyundan {candidates} tanesinin ≥ {min} incelemesi var ve {range} olumlu; en çok incelemesi olan {n} tanesi analiz edildi.",
  "Excluded non-games: {names}.": "Oyun olmadığı için çıkarılanlar: {names}.",
  "▲/▼ = score change since your previous run with these tags and filters.": "▲/▼ = bu etiket ve filtrelerle yaptığınız önceki taramadan beri puan değişimi.",
  "No games to show. Try a lower minimum or a wider % range.": "Gösterilecek oyun yok. Daha düşük bir en az değeri ya da daha geniş bir % aralığı deneyin.",
  "Game": "Oyun",
  "Score": "Puan",
  "Reviews": "İnceleme",
  "% Pos": "% Olumlu",
  "Last 12 mo": "Son 12 ay",
  "Reviews in the last 12 months (share of all reviews), and their % positive": "Son 12 aydaki incelemeler (tüm incelemeler içindeki payı) ve olumlu yüzdeleri",
  "Est. gross": "Tahmini brüt",
  "Top complaint": "En büyük şikayet",
  "Risks": "Riskler",
  ", {pct} pos": ", {pct} olumlu",
  " ({pct} adj.)": " ({pct} düzeltilmiş)",
  "Score {score}. How it is calculated": "Puan {score}. Nasıl hesaplandığı",
  "new": "yeni",
  "Not in your previous run with these tags": "Bu etiketlerle yaptığınız önceki taramada yoktu",
  "Change since your previous run with these tags and filters": "Bu etiket ve filtrelerle yaptığınız önceki taramadan beri değişim",
  "Report (.md)": "Rapor (.md)",
  "Table view": "Tablo görünümü",
  "Games": "Oyunlar",
  "Markets": "Pazarlar",

  // market strip and Markets view
  "Too few games with demand to judge this market.": "Bu pazarı değerlendirmek için talep gören oyun çok az.",
  "Many disappointed players and few good games: an underserved audience.": "Hayal kırıklığına uğramış çok oyuncu, az iyi oyun: karşılanmamış bir kitle.",
  "A mixed market: some good games already serve these players.": "Karışık bir pazar: bazı iyi oyunlar bu oyunculara zaten hitap ediyor.",
  "Mostly well served: players here already have good games.": "Çoğunlukla iyi karşılanmış: buradaki oyuncuların zaten iyi oyunları var.",
  "Games in tag": "Etiketteki oyunlar",
  "With demand": "Talep gören",
  "Underserved": "Karşılanmamış",
  "Well served ({pct}+)": "İyi karşılanmış ({pct}+)",
  "Gap": "Boşluk",
  "Underserved / (underserved + well served)": "Karşılanmamış / (karşılanmamış + iyi karşılanmış)",
  "Underserved $": "Karşılanmamış $",
  "Box Method (x45) gross of the underserved games": "Karşılanmamış oyunların Box Method (x45) brüt geliri",
  "Markets: which audiences are underserved?": "Pazarlar: hangi kitleler karşılanmamış?",
  "Which audiences are underserved? Rank every Steam tag by its games with demand that players rate poorly. Uses the Filters; the first build takes ~7 minutes, then ~1 day from the cache.": "Hangi kitleler karşılanmamış? Her Steam etiketini, talep görüp oyuncuların düşük puan verdiği oyunlarına göre sıralayın. Filtreleri kullanır; ilk oluşturma ~7 dakika sürer, sonra ~1 gün önbellekten gelir.",
  "Build market ranking": "Pazar sıralamasını oluştur",
  "Rebuild market ranking": "Pazar sıralamasını yeniden oluştur",
  "Building...": "Oluşturuluyor...",
  "Building the market ranking...": "Pazar sıralaması oluşturuluyor...",
  "Reading the Steam tag list": "Steam etiket listesi okunuyor",
  "{done} / {total} tags": "{done} / {total} etiket",
  "The market ranking was interrupted": "Pazar sıralaması yarıda kesildi",
  "Press Build market ranking again.": "Tekrar Pazar sıralamasını oluştur'a basın.",
  "Market ranking cancelled": "Pazar sıralaması iptal edildi",
  "Tags read so far stay cached, so the next build is faster.": "Şimdiye kadar okunan etiketler önbellekte kalır, bu yüzden sonraki oluşturma daha hızlı olur.",
  "Market ranking failed": "Pazar sıralaması başarısız oldu",
  "{n} tags, games with ≥ {min} reviews; underserved = {range} positive. Ranked by gap; broad tags (1,000+ games) and tags with under 3 underserved games come last. Click a tag to search it.": "{n} etiket, ≥ {min} incelemesi olan oyunlar; karşılanmamış = {range} olumlu. Boşluğa göre sıralı; geniş etiketler (1.000+ oyun) ve 3'ten az karşılanmamış oyunu olan etiketler en sonda. Aramak için bir etikete tıklayın.",
  "{n} tags SteamSpy can't search are left out (search them one by one).": "SteamSpy'ın arayamadığı {n} etiket dışarıda kaldı (onları tek tek arayın).",
  "{n} tags couldn't be read": "{n} etiket okunamadı",
  "They are missing from the ranking. Rebuild later to retry them.": "Bunlar sıralamada yok. Tekrar denemek için daha sonra yeniden oluşturun.",
  "Search {tag}": "{tag} ara",
  "Tag": "Etiket",
  "Games with at least the minimum reviews": "En az inceleme sayısına ulaşan oyunlar",
  "Games with demand inside the % positive range": "% olumlu aralığındaki talep gören oyunlar",
  "% positive of the median game with demand": "Talep gören ortanca oyunun olumlu yüzdesi",
  "Median % pos": "Ortanca % olumlu",

  // past runs
  "Past runs": "Geçmiş taramalar",
  "Saved runs": "Kayıtlı taramalar",
  "Loading...": "Yükleniyor...",
  "No saved runs yet. Finished searches appear here.": "Henüz kayıtlı tarama yok. Biten aramalar burada görünür.",
  "Markets: all tags": "Pazarlar: tüm etiketler",
  "{n} tags": "{n} etiket",
  "{n} game": "{n} oyun",
  "{n} games": "{n} oyun",
  "Delete this run": "Bu taramayı sil",
  "Delete run {label}": "{label} taramasını sil",
  "Couldn't load past runs": "Geçmiş taramalar yüklenemedi",
  "Couldn't delete the run": "Tarama silinemedi",
  "Still running": "Hâlâ sürüyor",
  "This run hasn't finished yet.": "Bu tarama henüz bitmedi.",
  "Couldn't open the run": "Tarama açılamadı",

  // score card
  "Opportunity score {score}": "Fırsat puanı {score}",
  "Proven demand + poor execution = high opportunity. Three parts, each 0-100%:": "Kanıtlanmış talep + kötü yapım = büyük fırsat. Üç parça, her biri %0-100:",
  "weight {pct}": "ağırlık {pct}",
  "Combined (weighted geometric mean)": "Birleşik (ağırlıklı geometrik ortalama)",
  "{label} (risk)": "{label} (risk)",
  "{part} is 0%, so the score is 0: a good opportunity needs all three parts.": "{part} %0, bu yüzden puan 0: iyi bir fırsat için üç parçanın da olması gerekir.",
  "If any part is 0%, the score is 0: a good opportunity needs all three parts.": "Herhangi bir parça %0 ise puan 0 olur: iyi bir fırsat için üç parçanın da olması gerekir.",

  // detail panel
  "Select a game on the map or in the table.": "Haritadan ya da tablodan bir oyun seçin.",
  "Steam store": "Steam mağazası",
  " · Released {date}": " · Çıkış {date}",
  "Opportunity score {score}. How it is calculated": "Fırsat puanı {score}. Nasıl hesaplandığı",
  "% positive": "% olumlu",
  "Last 12 months": "Son 12 ay",
  "Est. gross (x45)": "Tahmini brüt (x45)",
  "Range (x30-x100)": "Aralık (x30-x100)",
  "Review numbers: {source}": "İnceleme rakamları: {source}",
  "Demand": "Talep",
  "Dissatisfaction": "Memnuniyetsizlik",
  "Fixability": "Düzeltilebilirlik",
  "Risk penalty -{points} ({names})": "Risk cezası -{points} ({names})",
  "How is this score calculated?": "Bu puan nasıl hesaplanıyor?",
  "Complaints": "Şikayetler",
  "Core fantasy": "Ana fantezi",
  "History": "Geçmiş",
  "Review texts unavailable: {error}": "İnceleme metinleri alınamadı: {error}",
  "No English negative reviews to mine.": "İncelenecek İngilizce olumsuz inceleme yok.",
  "Great idea, bad execution?": "İyi fikir, kötü yapım mı?",
  "{pct} of {n} negative reviews still praise the idea or its potential.": "{n} olumsuz incelemenin {pct} kadarı yine de fikri ya da potansiyelini övüyor.",
  "{pct} of complaint mentions are fixable.": "Şikayetlerin {pct} kadarı düzeltilebilir.",
  "Half most helpful, half newest reviews ({n} negative from the last 12 months); reviews written under 2 h of play count half.": "Yarısı en faydalı, yarısı en yeni incelemeler (son 12 aydan {n} olumsuz); 2 saatten az oynanarak yazılan incelemeler yarım sayılır.",
  "Do: ": "Yap: ",
  "No positive-review phrases found.": "Olumlu incelemelerde ifade bulunamadı.",
  "Common phrases in {n} positive reviews": "{n} olumlu incelemede sık geçen ifadeler",
  "Players liked": "Oyuncuların sevdikleri",
  "No risk flags.": "Risk işareti yok.",
  "high": "yüksek",
  "warn": "uyarı",
  "info": "bilgi",
  "No review histogram available.": "İnceleme grafiği yok.",
  "{month}: {up} positive, {down} negative": "{month}: {up} olumlu, {down} olumsuz",
  "Positive": "Olumlu",
  "Negative": "Olumsuz",
  "Monthly reviews. A tall spike after launch can mean a streamer effect (mostly blue) or a review bomb (mostly red).": "Aylık incelemeler. Çıkıştan sonraki yüksek bir sıçrama yayıncı etkisi (çoğu mavi) ya da inceleme bombardımanı (çoğu kırmızı) olabilir.",
  "Opportunity summary": "Fırsat özeti",
  "Writing... (about a minute)": "Yazılıyor... (yaklaşık bir dakika)",
  "not written yet": "henüz yazılmadı",
  "Writing...": "Yazılıyor...",
  "Write summary": "Özeti yaz",
  "What players love, the complaints these games share, and what a better game would do. Written by the local model {model} (Ollama) from this ranking, in about a minute.": "Oyuncuların sevdiği, bu oyunların ortak şikayetleri ve daha iyi bir oyunun ne yapması gerektiği. Yerel model {model} (Ollama) bu sıralamadan yaklaşık bir dakikada yazar.",
  "Written by the local model {model}. It can be wrong: check each point against the games it names.": "Yerel model {model} yazdı. Yanılabilir: her maddeyi andığı oyunlarla karşılaştırın.",
  "What players love": "Oyuncuların sevdiği",
  "Shared complaints": "Ortak şikayetler",
  "A better game would": "Daha iyi bir oyun",
  "Caveats": "Dikkat",
  "The opportunity summary is being written.": "Fırsat özeti yazılıyor.",
  "Summary": "Özet",
  "A summary can be written for the games in the current ranking.": "Özet, geçerli sıralamadaki oyunlar için yazılabilir.",
  "Why players are unhappy, what a better game would do, and complaints no category covers. Written by the local model {model} (Ollama) in under a minute.": "Oyuncular neden mutsuz, daha iyi bir oyun ne yapmalı ve hiçbir kategoriye girmeyen şikayetler. Yerel model {model} (Ollama) bir dakikadan kısa sürede yazar.",
  "Written by the local model {model}. It can be wrong: check it against the reviews.": "Yerel model {model} yazdı. Yanılabilir: incelemelerle karşılaştırarak okuyun.",
  "Complaints no category covers": "Hiçbir kategoriye girmeyen şikayetler",
  "None found in the {n} negative reviews no category matched.": "Hiçbir kategoriye girmeyen {n} olumsuz incelemede başka şikayet bulunmadı.",
  "A summary is being written.": "Bir özet yazılıyor.",
  "under a minute left": "bir dakikadan az kaldı",
  "Presets:": "Hazır ayarlar:",
  "Default": "Varsayılan",
  "Proven demand": "Kanıtlı talep",
  "Quick look": "Hızlı bakış",
  "Shortlist": "Kısa liste",
  "Download CSV": "CSV indir",
  "From search": "Arama",
  "Note": "Not",
  "Remove from shortlist": "Kısa listeden çıkar",
  "Add to shortlist": "Kısa listeye ekle",
  "{n} starred games. Score, rating and complaint are from the search you starred them in.": "{n} yıldızlı oyun. Skor, puan ve şikayet, oyunu yıldızladığınız aramadan.",
  "No games yet. Star a game in the ranking (☆) to keep it here.": "Henüz oyun yok. Sıralamada bir oyunu yıldızlayın (☆), burada kalsın.",
  "Add a note...": "Not ekleyin...",
  "Note for {name}": "{name} için not",
  "Note saved": "Not kaydedildi",
  "Remove {name} from the shortlist": "{name} oyununu kısa listeden çıkar",
  "~{n} min left": "~{n} dk kaldı",
};

let lang = "en";
try { lang = localStorage.getItem("lang") === "tr" ? "tr" : "en"; } catch { /* storage blocked */ }
document.documentElement.lang = lang;

export const getLang = () => lang;

export function setLang(value) {
  lang = value === "tr" ? "tr" : "en";
  document.documentElement.lang = lang;
  try { localStorage.setItem("lang", lang); } catch { /* private mode: just not remembered */ }
}

// `text` in the current language, with {name} placeholders filled from `vars`.
export function t(text, vars) {
  const s = lang === "tr" ? (TR[text] ?? text) : text;
  return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s;
}

const locale = () => (lang === "tr" ? "tr-TR" : "en-US");
export const fmt = (n) => n.toLocaleString(locale()); // 1,460 / 1.460
export const pct = (share) => percent(share * 100); // 0.73 -> 73% / %73
export const percent = (p) => (lang === "tr" ? `%${Math.round(p)}` : `${Math.round(p)}%`);
export const decimal = (x, digits) => x.toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const dateTime = (seconds) => new Date(seconds * 1000).toLocaleString(lang === "tr" ? "tr-TR" : "en-GB",
  { dateStyle: "medium", timeStyle: "short" });

// Static page text: elements marked data-i18n (their text) and data-i18n-attr="title,placeholder,..."
// (those attributes). The English is read from the page once, then each call fills in the language.
const english = new WeakMap();
const squash = (s) => s.replace(/\s+/g, " ").trim();

export function applyStatic(root = document) {
  for (const node of root.querySelectorAll("[data-i18n], [data-i18n-attr]")) {
    if (!english.has(node)) {
      const attrs = {};
      for (const a of (node.dataset.i18nAttr || "").split(",").filter(Boolean)) attrs[a] = node.getAttribute(a);
      english.set(node, { text: node.hasAttribute("data-i18n") ? squash(node.textContent) : null, attrs });
    }
    const src = english.get(node);
    if (src.text != null) node.textContent = t(src.text);
    for (const [a, v] of Object.entries(src.attrs)) if (v != null) node.setAttribute(a, t(v));
  }
}
