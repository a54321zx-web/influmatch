import httpx, asyncio
async def test():
    r = await httpx.AsyncClient().get('https://railway-up-production-c373.up.railway.app/api/sync/pending', params={'secret':'040cd8b5285f2c3e930dbbc1bd0057a6500288013d0d723a'})
    print(r.text)
asyncio.run(test())
