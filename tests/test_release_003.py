import pytest
from supermarkt.categories import CATEGORIES, normalize_category
from supermarkt.http import HttpClient
from supermarkt.region import AldiRegionResolver
from supermarkt.sources.holab import OfficialHolabSource

@pytest.mark.parametrize(("source","expected"),[
    ("obst und gemüse","Obst & Gemüse"),("ALKOHOLFREIE GETRÄNKE","Getränke"),
    ("molkereiprodukte","Molkereiprodukte & Eier"),("tiernahrung","Tierbedarf"),
    ("Süßigkeiten","Snacks"),("unbekannte sonderaktion","Weitere Angebote"),
])
def test_category_normalization(source,expected):assert normalize_category(source)==expected

def test_category_vocabulary_is_stable_and_spelled_correctly():
    assert len(CATEGORIES)==18
    assert "Obst & Gemüse" in CATEGORIES and "Fisch & Meeresfrüchte" in CATEGORIES

@pytest.mark.parametrize(("postal","regions"),[
    ("01067",("nord",)),("28195",("nord",)),("46282",("nord",)),
    ("52062",("sued",)),("52068",("sued",)),("52070",("sued",)),("52080",("sued",)),
    ("52349",("sued",)),("52525",("sued",)),("45468",("sued",)),
    ("47179",("sued",)),("80331",("sued",)),
    ("51643",("nord","sued")),("57072",("nord","sued")),
])
def test_official_aldi_regression_evidence(postal,regions):
    resolver=AldiRegionResolver(HttpClient(5));resolved=resolver.detect(postal)
    assert resolver.last_regions==regions
    assert resolved==(regions[0] if len(regions)==1 else "auto")

class FakeHolabHttp(HttpClient):
    def __init__(self):super().__init__(5);self.urls=[]
    def get_bytes(self,url,headers=None):
        self.urls.append(url)
        if "/maerkte?" in url:
            return b'<li class="store"><a href="/maerkte/achim">Achim</a><span>28832</span></li>'
        return b'''<script type="application/ld+json">{"@graph":[{"makesOffer":[{"validFrom":"2026-08-24","validThrough":"2026-08-29"}]}]}</script><li class="offer"><h3 class="offer__title">Wasser</h3><span class="offer__subtitle">Mineralwasser</span><data class="offer__price" value="5.55"><span class="price-tag__prefix">ab 2 Kisten je</span></data><span class="offer__details">12 x 0.75 Ltr. + 3.30 Pfand/Kiste Ltr. 0.62</span><img src="/water.jpg"></li>'''

def test_holab_deposit_quantity_and_area():
    http=FakeHolabHttp();source=OfficialHolabSource(http);offers=source.load("28832")
    assert len(offers)==1 and offers[0].deposit==3.3 and offers[0].minimum_quantity==2
    assert not offers[0].comparison_eligible and offers[0].coverage_note
    assert "maerkte?q=28832" in http.urls[0]
    assert OfficialHolabSource(FakeHolabHttp()).load("80331")==[]


def test_holab_market_lookup_uses_requested_postal_code_not_default_map_area():
    http=FakeHolabHttp()
    http.get_bytes=lambda url,headers=None: (
        b'<li class="store"><a href="/maerkte/winsen-luhe">Winsen/Luhe</a><span>21423</span></li>'
        if "/maerkte?q=21423" in url else
        b'<li class="offer"><h3 class="offer__title">Wasser</h3><data class="offer__price" value="1.99"></data></li>'
    )

    offers=OfficialHolabSource(http).load("21423")

    assert len(offers)==1 and offers[0].retailer_url.endswith("/maerkte/winsen-luhe")
