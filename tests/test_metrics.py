def keyword_match(found, have):
    return len(have)/len(found)*100 if found else 0

def test_keyword_match():
    assert keyword_match(['python','react','sql'],['python','sql']) == 2/3*100

def test_no_keywords_is_zero():
    assert keyword_match([],[]) == 0
