import {KEYWORD_STORAGE_KEY,keywordDocument,normalizeKeywords,parseKeywordDocument} from "./keyword-filters.mjs";

const pageData=document.body.dataset,searchId=pageData.searchId,token=pageData.token;
const FILTER_STORAGE_KEY="korbklar.result-filters.v1",KEYWORD_ENABLED_KEY="korbklar.keyword-filter-enabled.v1";
const selectedPrograms=new Set((pageData.loyalty||"").split(",").filter(Boolean)),selectedRetailers=new Set(),offerById=new Map();
const $=id=>document.getElementById(id),esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let page=1,loading=false,done=false,category="",view="best_only",debounce=null,requestSeq=0,controller=null,lightboxTrigger=null,programsInitialized=false,keywords=[],keywordEnabled=false;

try{keywords=normalizeKeywords(JSON.parse(localStorage.getItem(KEYWORD_STORAGE_KEY)||"[]"))}catch(_error){}
try{const stored=localStorage.getItem(KEYWORD_ENABLED_KEY);keywordEnabled=stored===null?keywords.length>0:stored==="true"}catch(_error){}
try{const saved=JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY)||"{}");category=String(saved.category||"");if(["price","unit_price","retailer","product"].includes(saved.sort))$("sort").value=saved.sort;if(Array.isArray(saved.retailers))for(const name of saved.retailers)if(typeof name==="string"&&name)selectedRetailers.add(name)}catch(_error){}

function persistFilters(){try{localStorage.setItem(FILTER_STORAGE_KEY,JSON.stringify({category,sort:$("sort").value,retailers:[...selectedRetailers]}))}catch(_error){}}
function syncLoyaltyUrl(){const url=new URL(location.href),value=[...selectedPrograms].sort().join(",");value?url.searchParams.set("loyalty",value):url.searchParams.delete("loyalty");history.replaceState(null,"",url)}
function safeUrl(value){try{const u=new URL(value);return u.protocol==="https:"&&["www.lidl.de","lidl.de","www.rewe.de","shop.rewe.de"].includes(u.hostname.toLowerCase())?u.href:""}catch{return ""}}
function query(reset=false){
  if(reset){requestSeq++;controller?.abort();loading=false;page=1;done=false;offerById.clear();$("rows").innerHTML=""}
  if(loading||done)return;
  loading=true;const seq=requestSeq;controller=new AbortController();
  const params=new URLSearchParams({token,page:String(page),page_size:"100",q:$("q").value,category,sort:$("sort").value,view,loyalty:[...selectedPrograms].sort().join(",")});
  for(const retailer of selectedRetailers)params.append("retailers",retailer);
  if(keywordEnabled)for(const keyword of keywords)params.append("keywords",keyword);
  fetch(`/api/results/${encodeURIComponent(searchId)}?${params}`,{cache:"no-store",signal:controller.signal})
    .then(async response=>{if(!response.ok)throw new Error((await response.json().catch(()=>({}))).detail||`HTTP ${response.status}`);return response.json()})
    .then(data=>{if(seq!==requestSeq)return;render(data);page=data.page+1;done=!data.has_next;$("sentinel").textContent=done?"Alle passenden Angebote geladen.":"Weitere Angebote werden beim Scrollen geladen …"})
    .catch(error=>{if(error.name!=="AbortError"){$("sentinel").textContent=error.message;done=true}})
    .finally(()=>{if(seq===requestSeq)loading=false});
}

function persistKeywords(){try{localStorage.setItem(KEYWORD_STORAGE_KEY,JSON.stringify(keywords))}catch(_error){}renderKeywords();if(keywordEnabled)query(true)}
function renderKeywords(){
  $("keywordSummary").textContent=keywords.length?`${keywords.length} gespeichert`:"Keine gespeichert";
  const list=$("keywordList");
  list.replaceChildren(...keywords.map((keyword,index)=>{
    const row=document.createElement("div"),input=document.createElement("input"),remove=document.createElement("button");
    row.className="keywordRow";input.value=keyword;input.maxLength=80;input.ariaLabel=`Schlagwort ${keyword} bearbeiten`;
    input.onchange=()=>{keywords=normalizeKeywords(keywords.map((value,position)=>position===index?input.value:value));persistKeywords()};
    remove.type="button";remove.textContent="×";remove.ariaLabel=`Schlagwort ${keyword} löschen`;remove.onclick=()=>{keywords.splice(index,1);persistKeywords()};
    row.append(input,remove);return row;
  }));
}
function downloadKeywords(){const blob=new Blob([JSON.stringify(keywordDocument(keywords),null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download="korbklar-schlagworte.json";link.click();URL.revokeObjectURL(url)}

$("keywordEnabled").checked=keywordEnabled;
$("keywordEnabled").onchange=event=>{keywordEnabled=event.target.checked;try{localStorage.setItem(KEYWORD_ENABLED_KEY,String(keywordEnabled))}catch(_error){}query(true)};
$("keywordOpen").onclick=()=>$("keywordDialog").showModal();
$("keywordClose").onclick=()=>$("keywordDialog").close();
$("keywordDialog").addEventListener("click",event=>{if(event.target===$("keywordDialog"))$("keywordDialog").close()});
$("keywordForm").onsubmit=event=>{event.preventDefault();const before=keywords.length;keywords=normalizeKeywords([...keywords,$("keywordInput").value]);$("keywordInput").value="";$("keywordNotice").textContent=keywords.length===before?"Leeres oder doppeltes Schlagwort wurde nicht hinzugefügt.":"Schlagwort gespeichert.";persistKeywords()};
$("keywordExport").onclick=downloadKeywords;
$("keywordClear").onclick=()=>{keywords=[];$("keywordNotice").textContent="Schlagworte gelöscht.";persistKeywords()};
$("keywordImport").onchange=async event=>{try{const file=event.target.files?.[0];if(!file)return;if(file.size>65536)throw new Error("Die Schlagwortdatei ist größer als 64 KiB.");keywords=parseKeywordDocument(await file.text());$("keywordNotice").textContent=`${keywords.length} Schlagworte importiert.`;persistKeywords()}catch(error){$("keywordNotice").textContent=`Import fehlgeschlagen: ${error.message}`}finally{event.target.value=""}};
renderKeywords();

function render(data){
  $("table").classList.toggle("single-retailer",selectedRetailers.size===1);
  $("meta").textContent=`PLZ ${data.postal_code} · ${data.source_offer_count} Quellen-Treffer · Cache ${Math.floor(data.cache_age_seconds/60)} Min. alt`;
  $("marketBox").querySelector(".marketChange").href=`/?postal_code=${encodeURIComponent(data.postal_code)}`;
  const hidden=Number(data.hidden_count||0);$("stats").textContent=`${data.filtered_offer_count} passende Treffer · ${hidden} teurere Dubletten ${view==="all"?"eingeblendet":"ausgeblendet"}`;
  renderChips(data.retailer_counts);renderCategories(data.category_counts||{});renderPrograms(data.available_loyalty_programs||[],data.loyalty_note||"");renderMarkets(data.retailer_markets||[]);
  const warnings=data.warnings||[];$("warningsBox").hidden=!warnings.length;$("warnings").replaceChildren(...warnings.map(text=>Object.assign(document.createElement("div"),{textContent:text})));
  const fragment=document.createDocumentFragment();
  for(const offer of data.offers){
    offerById.set(offer.offer_id,offer);const row=document.createElement("div");row.className="row";
    const image=offer.image_url?`<button type="button" class="imageButton" data-src="${esc(offer.image_url)}" data-alt="${esc(offer.product)}"><img class="thumb" loading="lazy" src="${esc(offer.image_url)}" alt="${esc(offer.product)}"></button>`:`<div class="thumb" aria-hidden="true"></div>`,target=safeUrl(offer.product_url),linkLabel=offer.product_link_kind==="search"?"Offizielle Produktsuche":offer.product_link_kind==="market_offer"?"Angebotsseite des gewählten Markts":"",linkNote=target&&linkLabel?`<div class="small">${linkLabel}</div>`:"",product=target?`<a href="${esc(target)}" target="_blank" rel="noopener noreferrer">${esc(offer.product)}</a>${linkNote}`:esc(offer.product),deposit=offer.deposit_note?`<div class="small">${esc(offer.deposit_note)}</div>`:"",cashback=offer.cashback_credit_note?`<div class="small cashbackCredit">${esc(offer.cashback_credit_note)}</div>`:"",condition=offer.offer_condition?`<div class="small">${esc(offer.offer_condition)}</div>`:"";
    row.innerHTML=`<div>${image}</div><div class="retailer"><strong>${esc(offer.retailer)}</strong></div><div class="productblock"><div class="product">${product}</div><div class="categoryLabel">${esc(offer.category)}</div><div class="small">${esc(offer.description)}</div>${condition}<button type="button" class="shoppingAdd" data-offer-id="${esc(offer.offer_id)}">Zur Einkaufsliste</button></div><div class="regularPrice price ${esc(offer.regular_comparison_state)}" data-label="Ohne Bonus">${esc(offer.regular_price_text)}</div><div class="selectedPrice price ${esc(offer.selected_comparison_state)}" data-label="Mit Bonuswahl">${esc(offer.effective_price_text)}${cashback}${deposit}</div><div class="details"><div>${esc(offer.pack)}</div><div class="small">${esc(offer.unit_price)}</div></div><div class="validity small">${esc(offer.validity)}</div>`;
    fragment.appendChild(row);
  }
  $("rows").appendChild(fragment);
}
function renderChips(counts){
  const box=$("chips"),entries=Object.entries(counts||{});box.innerHTML="";
  const add=(name,count)=>{const button=document.createElement("button"),active=name?selectedRetailers.has(name):selectedRetailers.size===0;button.className="chip"+(active?" active":"");button.ariaPressed=String(active);button.textContent=name?`${name} · ${count}`:`Alle Händler · ${entries.reduce((sum,[,number])=>sum+number,0)}`;button.onclick=event=>{if(!name)selectedRetailers.clear();else if(event.shiftKey){selectedRetailers.has(name)?selectedRetailers.delete(name):selectedRetailers.add(name)}else{selectedRetailers.clear();selectedRetailers.add(name)}category="";persistFilters();query(true)};box.appendChild(button)};
  add("",0);entries.sort((a,b)=>a[0].localeCompare(b[0],"de")).forEach(([name,count])=>add(name,count));
}
function renderCategories(counts){const select=$("category"),current=category;select.innerHTML='<option value="">Alle Kategorien</option>';Object.entries(counts).sort((a,b)=>a[0].localeCompare(b[0],"de")).forEach(([name,count])=>select.add(new Option(`${name} · ${count}`,name)));select.value=current;if(current&&!select.value){category="";persistFilters()}}
function renderMarkets(markets){const box=$("marketBox"),list=$("marketList");box.hidden=!markets.length;list.replaceChildren(...markets.map(market=>{const item=document.createElement("li"),strong=document.createElement("strong");strong.textContent=`${market.retailer}: `;item.append(strong,document.createTextNode(market.label));return item}))}
function updateLoyaltySummary(){const selected=[...$("loyaltyPrograms").querySelectorAll("input:checked")].map(input=>input.nextElementSibling?.textContent).filter(Boolean);$("loyaltySummary").textContent=selected.length?selected.join(", "):"Keine ausgewählt"}
function renderPrograms(programs,note){
  const box=$("loyaltyBox"),list=$("loyaltyPrograms");box.hidden=!programs.length;$("loyaltyNote").textContent=note;if(programsInitialized){updateLoyaltySummary();return}programsInitialized=true;list.replaceChildren();
  for(const program of programs){const label=document.createElement("label"),input=document.createElement("input"),span=document.createElement("span");input.type="checkbox";input.dataset.program=program.id;input.checked=selectedPrograms.has(program.id);span.textContent=program.label;input.onchange=()=>{input.checked?selectedPrograms.add(program.id):selectedPrograms.delete(program.id);updateLoyaltySummary();syncLoyaltyUrl();query(true)};label.append(input,span);list.append(label)}
  $("loyaltyAll").onclick=()=>{list.querySelectorAll("input").forEach(input=>{input.checked=true;selectedPrograms.add(input.dataset.program)});updateLoyaltySummary();syncLoyaltyUrl();query(true)};
  $("loyaltyNone").onclick=()=>{list.querySelectorAll("input").forEach(input=>input.checked=false);selectedPrograms.clear();updateLoyaltySummary();syncLoyaltyUrl();query(true)};updateLoyaltySummary();
}

$("rows").addEventListener("click",event=>{const button=event.target.closest(".imageButton");if(!button)return;lightboxTrigger=button;$("lightboxImage").src=button.dataset.src;$("lightboxImage").alt=button.dataset.alt;$("lightboxTitle").textContent=button.dataset.alt;document.documentElement.classList.add("modalOpen");$("lightbox").showModal();$("lightboxClose").focus()});
$("rows").addEventListener("click",async event=>{const button=event.target.closest(".shoppingAdd");if(!button)return;button.disabled=true;await globalThis.KorbKlarShopping.addOffer(offerById.get(button.dataset.offerId));button.textContent="Hinzugefügt ✓";setTimeout(()=>{button.disabled=false;button.textContent="Zur Einkaufsliste"},1200)});
function closeLightbox(){$("lightbox").close();document.documentElement.classList.remove("modalOpen");$("lightboxImage").src="";lightboxTrigger?.focus()}
$("lightboxClose").onclick=closeLightbox;$("lightbox").addEventListener("click",event=>{if(event.target===$("lightbox"))closeLightbox()});$("lightbox").addEventListener("cancel",event=>{event.preventDefault();closeLightbox()});
$("q").addEventListener("input",()=>{clearTimeout(debounce);debounce=setTimeout(()=>query(true),300)});
$("category").onchange=event=>{category=event.target.value;persistFilters();query(true)};
$("sort").onchange=()=>{persistFilters();query(true)};
document.querySelectorAll(".viewTab").forEach(button=>button.onclick=()=>{view=button.dataset.view;document.querySelectorAll(".viewTab").forEach(item=>item.classList.toggle("active",item===button));query(true)});
new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting))query()},{rootMargin:"600px"}).observe($("sentinel"));query(true);
document.querySelectorAll(".mainTab").forEach(button=>button.onclick=()=>{document.querySelectorAll(".mainTab").forEach(item=>item.classList.toggle("active",item===button));$("resultsPanel").hidden=button.dataset.panel!=="resultsPanel";$("shoppingPanel").hidden=button.dataset.panel!=="shoppingPanel"});
