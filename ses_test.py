import asyncio
import edge_tts

METIN = "Hello! I'm Pip. Shall we count together? One, two, three!"
ADAYLAR = ["en-GB-SoniaNeural", "en-GB-MaisieNeural", "en-GB-LibbyNeural"]

async def dene(ses):
    c = edge_tts.Communicate(METIN, ses, rate="-10%", boundary="WordBoundary")
    kelime = 0
    with open(ses + ".mp3", "wb") as f:
        async for ch in c.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                kelime += 1
    return kelime

async def main():
    try:
        v = await edge_tts.list_voices()
        print("MEVCUT en-GB SESLER:", sorted(x["ShortName"] for x in v if x["Locale"] == "en-GB"))
    except Exception as e:
        print("Liste alinamadi:", type(e).__name__, e)
    for s in ADAYLAR:
        try:
            n = await dene(s)
            print("OK:", s, "-", n, "kelime")
        except Exception as e:
            print("YOK:", s, "-", type(e).__name__, e)

asyncio.run(main())