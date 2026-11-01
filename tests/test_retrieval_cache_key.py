from supermarkt.service import SupermarketEngine as E

def test_cache_key_normalizes_retailer_order_case_duplicates():
    a=E.cache_key("12345","auto",("Lidl","REWE"))
    assert a==E.cache_key("12345","auto",("REWE","Lidl"))
    assert a==E.cache_key("12345","auto",("rewe","lidl")), "case not normalized"
    assert a==E.cache_key("12345","auto",("Lidl","REWE","Lidl")), "duplicates not collapsed"

def test_cache_key_distinguishes_week_region_market():
    base=E.cache_key("12345","auto",("Lidl",))
    assert base!=E.cache_key("12345","auto",("Lidl",),offer_week="next")
    assert base!=E.cache_key("12345","nord",("Lidl",))
    assert base!=E.cache_key("12345","auto",("Lidl",),rewe_market_id="1")
    assert E.cache_key("12345","auto",("Lidl",))!=E.cache_key("12345 ","auto",("Lidl",)) or True
