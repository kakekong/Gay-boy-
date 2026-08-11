"""Quoted replies and forwarding, on both conversation surfaces.

The features are WhatsApp-shaped, but the interesting part here is that both
of them are ways to move text between conversations, and this app has
deliberate walls between conversations. So the checks below are mostly about
what a quote and a forward may NOT do:

* A quote may only cite a message from the same channel / the same document
  thread. Quoting an arbitrary id would let anyone copy a line out of a
  conversation they were never in, just by replying to it somewhere they are.
* A forward requires read access to the source and membership of the
  destination — a director may read any channel from the monitor view, but may
  not post into one they never joined.
* Forwarding to a person opens a DM. That used to mean obeying the
  cross-department approval rule; that rule is gone — talking to a colleague
  is not a decision — so a forward now opens the conversation it needs. The
  wall that stays is membership: you may not post into a channel you are not
  in, whoever you are.
* A forwarded message names the original author and nothing else. It must not
  carry the quotation number, the customer, or the channel it came from — that
  is what would turn a forward into a hole in the scoping rules.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:150]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

# Every asserted body carries the run tag. These drivers are re-run against a
# dirty DB all the time, and "find the message that says X" quietly matches the
# copy left behind by the previous run — which reads exactly like a bug.
LONG = "spec sheet: " + "x" * 400


async def msgs(c, hdrs, ch):
    return J(await c.get(f"/chat/channels/{ch}/messages", headers=hdrs))


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=60)
    d=await login(c,"director@demo.local");  s1=await login(c,"sales1@demo.local")
    s2=await login(c,"sales2@demo.local");   pu=await login(c,"purchasing@demo.local")
    hr=await login(c,"hr@demo.local")
    tag=uuid.uuid4().hex[:5]
    SECRET = f"PT Rahasia {tag} sells at 9,000,000 — keep the cost to ourselves"
    ASK    = f"can you take the Friday delivery? [{tag}]"
    ACK    = f"yes, booked [{tag}]"
    LEAD   = f"supplier confirmed 6 weeks lead time [{tag}]"
    NOTE   = f"FYI for planning [{tag}]"

    # Read the directory as the director: /chat/contacts excludes the caller,
    # and the ids of both sales reps are needed below.
    id_of={u["full_name"]:u["id"] for u in J(await c.get("/chat/contacts",headers=d))}
    s2_id, hr_id, pu_id = id_of["Sales Two"], id_of["HR Demo"], id_of["Purchasing Demo"]

    # ─── channels ────────────────────────────────────────────────────────────
    # sales1 ↔ sales2: same department, anyone may start it.
    ch1=J(await c.post(f"/chat/dm/{s2_id}",headers=s1))["id"]
    # director ↔ purchasing: cross-department, so only the director could open it.
    ch2=J(await c.post(f"/chat/dm/{pu_id}",headers=d))["id"]
    ch3=J(await c.post("/chat/channels",headers=d,
                       json={"name":f"Ops {tag}","member_ids":[id_of["Sales One"],s2_id]}))["id"]

    # ─── 1. replying to a specific message ───────────────────────────────────
    m1=J(await c.post(f"/chat/channels/{ch1}/messages",headers=s1,
                      json={"body":ASK}))
    r=await c.post(f"/chat/channels/{ch1}/messages",headers=s2,
                   json={"body":ACK,"reply_to_id":m1["id"]})
    check("a reply quoting a message in the same channel is accepted", r.status_code==201, J(r))
    q=J(r).get("reply_to") or {}
    check("the reply carries the quoted message back", q.get("id")==m1["id"], str(q))
    check("the quote names who wrote it", q.get("user_name")=="Sales One", str(q.get("user_name")))
    check("the quote carries the quoted text", "Friday" in (q.get("body") or ""), str(q.get("body")))

    rows=await msgs(c,s2,ch1)
    reply=[m for m in rows if m["body"]==ACK][0]
    check("the quote survives a reload", (reply.get("reply_to") or {}).get("id")==m1["id"],
          str(reply.get("reply_to")))
    check("an ordinary message has no quote",
          next(m for m in rows if m["id"]==m1["id"]).get("reply_to") is None)

    # A long quote is trimmed — a preview, not a way to paste a whole message
    # somewhere it hasn't been.
    long_m=J(await c.post(f"/chat/channels/{ch1}/messages",headers=s1,json={"body":LONG}))
    r=J(await c.post(f"/chat/channels/{ch1}/messages",headers=s2,
                     json={"body":"got it","reply_to_id":long_m["id"]}))
    body=(r.get("reply_to") or {}).get("body") or ""
    check("a long quote is truncated to a preview", len(body)<=180 and body.endswith("…"),
          f"len={len(body)}")

    # ─── 2. a quote cannot reach into another conversation ───────────────────
    m2=J(await c.post(f"/chat/channels/{ch2}/messages",headers=d,
                      json={"body":"internal: margin is thin on this one"}))
    check("sales cannot even read the other channel",
          (await c.get(f"/chat/channels/{ch2}/messages",headers=s1)).status_code==403)
    r=await c.post(f"/chat/channels/{ch1}/messages",headers=s1,
                   json={"body":"look at this","reply_to_id":m2["id"]})
    check("quoting a message from another channel is rejected", r.status_code==400, str(r.status_code))
    check("...and its text did not leak in the error",
          "margin is thin" not in r.text, r.text[:100])
    r=await c.post(f"/chat/channels/{ch1}/messages",headers=s1,
                   json={"body":"?","reply_to_id":str(uuid.uuid4())})
    check("quoting an id that doesn't exist is rejected", r.status_code==400, str(r.status_code))

    # A deleted message still anchors the replies that quoted it.
    await c.delete(f"/chat/messages/{m1['id']}",headers=s1)
    rows=await msgs(c,s2,ch1)
    reply=[m for m in rows if m["body"]==ACK][0]
    check("a reply to a deleted message shows it as deleted",
          (reply.get("reply_to") or {}).get("deleted") is True, str(reply.get("reply_to")))
    check("...and the deleted text is gone from the quote",
          "Friday" not in str(reply.get("reply_to")), str(reply.get("reply_to")))

    # ─── 3. forwarding a chat message ────────────────────────────────────────
    src=J(await c.post(f"/chat/channels/{ch1}/messages",headers=s1,
                       json={"body":LEAD}))
    r=await c.post(f"/chat/messages/{src['id']}/forward",headers=s1,
                   json={"channel_ids":[ch3]})
    check("forwarding into a channel you're in works", r.status_code==200, J(r))
    check("it reports one delivery", J(r).get("count")==1, str(J(r)))

    rows=await msgs(c,s2,ch3)
    fwd=[m for m in rows if tag in m["body"] and "lead time" in m["body"]]
    check("the forwarded message arrives in the destination", len(fwd)==1, str(len(fwd)))
    if fwd:
        check("it is flagged as forwarded", bool(fwd[0].get("forwarded")), str(fwd[0].get("forwarded")))
        check("it credits the original author",
              (fwd[0]["forwarded"] or {}).get("author_name")=="Sales One",
              str(fwd[0].get("forwarded")))
        check("it is attributed to whoever forwarded it",
              fwd[0]["user_name"]=="Sales One", str(fwd[0]["user_name"]))
        check("the origin conversation is NOT named", str(ch1) not in str(fwd[0]), str(fwd[0])[:160])

    # A note rides along as its own message, after the forward.
    r=await c.post(f"/chat/messages/{src['id']}/forward",headers=s1,
                   json={"channel_ids":[ch3],"note":NOTE})
    rows=await msgs(c,s2,ch3)
    bodies=[m["body"] for m in rows]
    check("a note is delivered alongside the forward", NOTE in bodies, str(bodies[-3:]))
    if NOTE in bodies:
        check("the note lands after the forwarded message",
              bodies.index(NOTE) > max(i for i,b in enumerate(bodies) if tag in b and "lead time" in b),
              str(bodies[-3:]))
        note=[m for m in rows if m["body"]==NOTE][-1]
        check("the note itself is not marked forwarded", note.get("forwarded") is None)

    # ─── 4. forward permissions ──────────────────────────────────────────────
    r=await c.post(f"/chat/messages/{src['id']}/forward",headers=s1,
                   json={"channel_ids":[ch2]})
    check("you cannot forward into a channel you're not in", r.status_code==403, str(r.status_code))
    r=await c.post(f"/chat/messages/{m2['id']}/forward",headers=s1,
                   json={"channel_ids":[ch1]})
    check("you cannot forward a message you cannot read", r.status_code in (403,404), str(r.status_code))
    r=await c.post(f"/chat/messages/{src['id']}/forward",headers=s1,json={})
    check("a forward with no destination is rejected", r.status_code==400, str(r.status_code))

    # The director can read any channel from the monitor view, but reading is
    # not joining: they still cannot post into one.
    r=await c.post(f"/chat/messages/{src['id']}/forward",headers=d,
                   json={"channel_ids":[ch1]})
    check("even the director cannot forward into a channel they never joined",
          r.status_code==403, str(r.status_code))
    check("...though they can read the source to forward it elsewhere",
          (await c.post(f"/chat/messages/{src['id']}/forward",headers=d,
                        json={"channel_ids":[ch2]})).status_code==200)

    # ─── 5. forwarding to a person opens a DM, under the same rules ──────────
    before=len(J(await c.get("/chat/channels",headers=s1)))
    r=await c.post(f"/chat/messages/{src['id']}/forward",headers=s1,
                   json={"user_ids":[s2_id]})
    check("forwarding to someone you already DM reuses that conversation",
          r.status_code==200 and J(r)["delivered"][0]["channel_id"]==str(ch1), str(J(r)))
    check("...and does not create a new channel",
          len(J(await c.get("/chat/channels",headers=s1)))==before)

    # Forwarding across departments used to be refused unless you were the
    # director — the same approval gate that fronted starting the chat. Both
    # are gone: talking to a colleague is not a decision, and a forward that
    # is refused just gets screenshotted into WhatsApp instead.
    r=await c.post(f"/chat/messages/{src['id']}/forward",headers=s1,
                   json={"user_ids":[hr_id]})
    check("sales can forward to another department, opening the DM",
          r.status_code==200, f"{r.status_code} {r.text[:140]}")
    check("...and it was actually delivered somewhere",
          J(r).get("count")==1 and J(r)["delivered"][0].get("channel_id"),
          str(J(r))[:150])
    r=await c.post(f"/chat/messages/{src['id']}/forward",headers=d,
                   json={"user_ids":[hr_id]})
    check("the director may too, as before", r.status_code==200, J(r))

    targets=J(await c.get("/chat/forward-targets",headers=s1))
    by_name={x["full_name"]:x for x in targets.get("contacts",[])}
    check("the picker lists the conversations you're in",
          {str(ch1),str(ch3)} <= {x["id"] for x in targets.get("channels",[])},
          str([x["title"] for x in targets.get("channels",[])]))
    check("the picker allows a same-department colleague",
          by_name.get("Sales Two",{}).get("can_dm") is True, str(by_name.get("Sales Two")))
    check("the picker no longer greys out a cross-department colleague",
          by_name.get("HR Demo",{}).get("can_dm") is True, str(by_name.get("HR Demo")))
    check("the picker never offers portal accounts",
          not any(x["role"] in ("customer","supplier") for x in targets.get("contacts",[])))

    # ─── 6. forwarding a forward keeps the true author ───────────────────────
    rows=await msgs(c,s2,ch3)
    already=[m for m in rows if tag in m["body"] and "lead time" in m["body"]][0]
    r=await c.post(f"/chat/messages/{already['id']}/forward",headers=s2,
                   json={"channel_ids":[ch1]})
    check("a forwarded message can be forwarded on", r.status_code==200, J(r))
    rows=await msgs(c,s1,ch1)
    onward=[m for m in rows if tag in m["body"] and "lead time" in m["body"] and m.get("forwarded")][-1]
    check("the chain still credits the original author, not the last sender",
          (onward["forwarded"] or {}).get("author_name")=="Sales One",
          str(onward.get("forwarded")))
    check("...while the message itself is attributed to the sender",
          onward["user_name"]=="Sales Two", str(onward["user_name"]))

    # ─── 7. the same two features on a document discussion ───────────────────
    cust=J(await c.post("/customers",headers=s1,json={"company_name":f"PT Rahasia {tag}","industry":"mining"}))["id"]
    pr=J(await c.post("/price-requests",headers=s1,json={"customer_id":cust,
        "items":[{"description":"Gearbox","qty":1,"uom":"pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit",headers=s1)
    await c.post(f"/price-requests/{pr}/price",headers=pu,json={"items":[{"line_no":1,"cost_price":5000000,"basis":"unit"}]})
    await c.post(f"/price-requests/{pr}/approve",headers=d,json={"items":[{"line_no":1,"sell_price":9000000,"basis":"unit"}]})
    quo=J(await c.post(f"/quotations/from-price-request/{pr}",headers=s1))["id"]
    quo_no=J(await c.get(f"/quotations/{quo}",headers=s1)).get("number")

    c1=J(await c.post("/comments",headers=s1,
                      json={"owner_type":"quotation","owner_id":quo,"body":SECRET}))
    r=await c.post("/comments",headers=s1,json={"owner_type":"quotation","owner_id":quo,
        "body":"agreed, hold that line","reply_to_id":c1["id"]})
    check("a discussion reply can quote an earlier message", r.status_code==201, J(r))
    dq=J(r).get("reply_to") or {}
    check("the discussion quote carries author + text",
          dq.get("author_name")=="Sales One" and "9,000,000" in (dq.get("body") or ""), str(dq))
    rows=J(await c.get("/comments",headers=s1,params={"owner_type":"quotation","owner_id":quo}))
    check("the discussion quote survives a reload",
          any((x.get("reply_to") or {}).get("id")==c1["id"] for x in rows))

    # A quote from a different thread must not be citable here — even when the
    # same person can read both, since the readers of this thread may not be
    # able to read the other one.
    other=J(await c.post("/comments",headers=s1,
                         json={"owner_type":"price_request","owner_id":pr,
                               "body":"costing note on the request"}))
    r=await c.post("/comments",headers=s1,json={"owner_type":"quotation","owner_id":quo,
        "body":"see this","reply_to_id":other["id"]})
    check("quoting a message from another document's thread is rejected",
          r.status_code==400, str(r.status_code))

    # A mention that is a reply arrives with the line it answers.
    r=await c.post("/comments",headers=s1,json={"owner_type":"quotation","owner_id":quo,
        "body":"@Purchasing Demo does 6 weeks still hold?","mention_user_ids":[pu_id],
        "reply_to_id":c1["id"]})
    check("a mention can be a reply", r.status_code==201, J(r))
    inbox=[m for m in J(await c.get("/comments/mentions",headers=pu))
           if str(m.get("owner_id"))==str(quo)]
    check("the mentions inbox shows what the reply was answering",
          bool(inbox) and bool((inbox[0].get("reply_to") or {}).get("body")),
          str(inbox[0].get("reply_to") if inbox else None))

    # ─── 8. forwarding out of a document thread lands in chat ────────────────
    r=await c.post(f"/comments/{c1['id']}/forward",headers=s1,json={"channel_ids":[ch1]})
    check("a discussion message can be forwarded into a chat", r.status_code==200, J(r))
    rows=await msgs(c,s2,ch1)
    got=[m for m in rows if m["body"]==SECRET]
    check("the recipient sees it in their chat", len(got)==1, str(len(got)))
    if got:
        check("it is credited to the original author",
              (got[0].get("forwarded") or {}).get("author_name")=="Sales One",
              str(got[0].get("forwarded")))
        check("the quotation number is NOT carried across",
              not quo_no or quo_no not in str(rows), str(quo_no))
        check("neither is the document id", str(quo) not in str(rows))

    # Someone holding the thread only through a mention may still forward from
    # it — into a conversation they are already part of.
    r=await c.post(f"/comments/{c1['id']}/forward",headers=pu,json={"channel_ids":[ch2]})
    check("a mentioned outsider can forward from the thread they hold",
          r.status_code==200, J(r))
    r=await c.post(f"/comments/{c1['id']}/forward",headers=hr,json={"channel_ids":[ch2]})
    check("someone with no part in the thread cannot forward from it",
          r.status_code==403, str(r.status_code))

    # ─── 9. the trail ────────────────────────────────────────────────────────
    audit=J(await c.get("/audit",headers=d,params={"action":"forward","limit":50}))
    kinds={a["entity"] for a in audit} if isinstance(audit,list) else set()
    check("forwards are written to the audit log",
          {"chat_message","comment_message"} <= kinds, str(kinds))
    if isinstance(audit,list) and audit:
        one=[a for a in audit if a["entity"]=="comment_message"][0]
        check("the audit row records who did it and where it went",
              bool(one.get("actor_name")) and bool((one.get("after") or {}).get("channels")),
              str(one)[:160])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())
