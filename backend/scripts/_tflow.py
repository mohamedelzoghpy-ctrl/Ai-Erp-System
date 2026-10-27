# get or create warehouses
req = urllib.request.Request('http://127.0.0.1:8000/warehouses', headers={'Authorization': 'Bearer ' + TOKEN})
whs = json.loads(urllib.request.urlopen(req).read())
if len(whs) < 2:
    # create second
    payload = {'name': 'Shop', 'code': 'W2'}
    req = urllib.request.Request('http://127.0.0.1:8000/warehouses', data=json.dumps(payload).encode(), headers=H, method='POST')
    whs.append(json.loads(urllib.request.urlopen(req).read()))
w1, w2 = whs[0], whs[1]