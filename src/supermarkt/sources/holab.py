from __future__ import annotations
import json, re
from urllib.parse import urlencode, urljoin
from ..common import build_match_key, clean_text, format_validity, normalize_pack, parse_base_price_text, parse_deposit_text, parse_iso_date, parse_number
from ..http import HttpClient
from ..models import Offer, ToolError

class OfficialHolabSource:
    BASE="https://holab.de"; MARKETS_URL=BASE+"/maerkte"; OFFERS_URL=BASE+"/angebote"; MAX_RESPONSE=2_000_000
    def __init__(self,http:HttpClient)->None:self.http=http;self.last_market_url="";self.last_market_label=""
    def _html(self,url:str)->str:
        data=self.http.get_bytes(url,{"Accept":"text/html"})
        if len(data)>self.MAX_RESPONSE:raise ToolError("HOL’AB!-Antwort überschreitet das Größenlimit")
        return data.decode("utf-8",errors="replace")
    def load(self,postal_code:str)->list[Offer]:
        try:from bs4 import BeautifulSoup
        except Exception as exc:raise ToolError(f"HOL’AB! benötigt BeautifulSoup: {exc}") from exc
        markets_url=f"{self.MARKETS_URL}?{urlencode({'q':postal_code})}"
        markets=BeautifulSoup(self._html(markets_url),"html.parser")
        market=next((n for n in markets.select("li.store a[href*='/maerkte/']") if postal_code in clean_text(n.find_parent("li").get_text(" ",strip=True) if n.find_parent("li") else "")),None)
        if market is None:return []
        self.last_market_url=urljoin(self.BASE,clean_text(market.get("href")));self.last_market_label=clean_text(market.get_text(" ",strip=True)) or "HOL’AB!"
        page=BeautifulSoup(self._html(self.OFFERS_URL),"html.parser");periods={};all_periods=set()
        for script in page.select('script[type="application/ld+json"]'):
            try:payload=json.loads(script.string or "")
            except (TypeError,json.JSONDecodeError):continue
            for node in payload.get("@graph",()) if isinstance(payload,dict) else ():
                offers=node.get("makesOffer",()) if isinstance(node,dict) else ()
                for offered in offers:
                    period = parse_iso_date(offered.get("validFrom")), parse_iso_date(offered.get("validThrough"))
                    all_periods.add(period)
                    name_key = re.sub(r"[^\w]", "", clean_text(offered.get("name")).casefold())
                    if name_key:
                        periods[name_key] = period
        result=[]
        for index,card in enumerate(page.select("li.offer, div.offer"),1):
            def text(selector, card=card):
                node=card.select_one(selector);return clean_text(node.get_text(" ",strip=True) if node else "")
            name=text(".offer__title");subtitle=text(".offer__subtitle");price_node=card.select_one("data.offer__price");price=parse_number(price_node.get("value") if price_node else None);details=text(".offer__details")
            if not name or price is None or price<=0:continue
            name_key = re.sub(r"[^\w]", "", name.casefold())
            start, end = periods.get(name_key, next(iter(all_periods)) if len(all_periods) == 1 else (None, None))
            if start and end and start > end:
                raise ToolError("HOL’AB! lieferte eine widersprüchliche Artikelgültigkeit")
            prefix=clean_text(price_node.select_one(".price-tag__prefix").get_text(" ",strip=True) if price_node and price_node.select_one(".price-tag__prefix") else "");minimum_match=re.search(r"ab\s*(\d{1,2})\s*kisten",prefix,re.I);minimum=int(minimum_match[1]) if minimum_match and int(minimum_match[1])>1 else None;deposit=parse_deposit_text(details);base_price,base_unit=parse_base_price_text(details);image=card.select_one("img[src]");image_url=urljoin(self.BASE,clean_text(image.get("src"))) if image else "";offer_id=f"holab:{index}:{re.sub(r'[^a-z0-9]+','-',name.casefold()).strip('-')}";pack=normalize_pack(details)
            single_match = re.search(r"1\s*Kiste\s*(\d+[,.]\d{2})", details, re.I)
            single_price = parse_number(single_match[1]) if single_match else None
            result.append(Offer(multi_buy_quantity=minimum,
                multi_buy_total_price=round(price * minimum, 2) if minimum else None,
                single_price=single_price, pack_size=pack,
                multi_buy_condition=prefix, offer_id=offer_id,retailer="HOL’AB!",category="Getränke",name=name,brand="",description=subtitle,price=price,base_price=base_price,base_unit=base_unit,pack_signature=pack,validity_label=format_validity(start,end),match_key=build_match_key("",name,pack,offer_id),source_url=self.OFFERS_URL,product_url=self.OFFERS_URL,retailer_url=self.last_market_url,image_url=image_url,deposit=deposit,minimum_quantity=minimum,offer_condition=prefix,comparison_eligible=minimum is None,coverage_note="Ausgewählte Wochenangebote; nicht der vollständige Prospekt" + ("; Gültigkeit nicht vollständig veröffentlicht" if not (start and end) else ""),valid_from=start.isoformat() if start else None,valid_until=end.isoformat() if end else None))
        if not result:raise ToolError("HOL’AB! lieferte keine lesbaren ausgewählten Angebote")
        return result
