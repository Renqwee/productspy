#!/usr/bin/env python3
"""
verify_amazon.py — التحقق الحي بعد التعديلات.

يمر على أربعة منتجات من ثلاثة نطاقات عبر واجهة المكتبة العامة
(get_product_info) لا عبر الـ tracker مباشرة — عشان يختبر السلسلة
كاملة: registry -> base.fetch -> Fetcher.get -> validator -> recover.

كل منتج يُطلب **مرتين**: الأولى تدفع ثمن تثبيت بلد التوصيل (طلب
إضافي)، والثانية المفروض تتخطاه لأن التثبيت لكل (fetcher, host).
فرق الزمن بين النداءين هو الدليل على أن التثبيت ما يتكرر.

توقعات مكتوبة مسبقاً لكل منتج، والسكربت يقارن ويصرخ عند الاختلاف.
الرقم الوحيد المجهول عمداً هو السعر الألماني — لأنه المفروض يتغيّر.
"""

from __future__ import annotations

import inspect
import time
import traceback
from decimal import Decimal

CASES = [
    {
        "label": "sa / كرسي إيفوماو",
        "url": "https://www.amazon.sa/dp/B0FWXZLD6F",
        "currency": "SAR",
        "price": Decimal("1349.10"),      # متحقق: 1499 × 0.9، والموقع يعلن -10%
        "list_price": Decimal("1499.00"),
        "note": "لو تغيّر السعر فهو تغيّر حقيقي في الموقع لا خطأ استخراج",
    },
    {
        "label": "sa / لابتوب أسوس (بائع خارجي)",
        "url": "https://www.amazon.sa/dp/B0CDL3CQHV",
        "currency": "SAR",
        "price": Decimal("6365.35"),
        "list_price": None,
        "note": "بائع Desertcart SA، توفر 'يشحن خلال 7 إلى 8 أيام'",
    },
    {
        "label": "de / سيرفس برو",
        "url": "https://www.amazon.de/dp/B09WVVZQD3",
        "currency": "EUR",
        "price": None,                    # مجهول عمداً — هذا بيت القصيد
        "list_price": None,
        "note": (
            "قبل تثبيت البلد كان €314,89 = 1,363.86 ريال ÷ 4.33، أي سعر "
            "التصدير محوّلاً لا السعر الألماني. لو رجع 314.89 مرة ثانية "
            "فالتثبيت فشل. **افتح الصفحة بعينك وقارن.**"
        ),
    },
    {
        "label": "uk / يد بلايستيشن",
        "url": "https://www.amazon.co.uk/dp/B07TCB5DBG",
        "currency": "GBP",
        "price": None,                    # مجهول: كان محجوباً كلياً
        "list_price": None,
        "note": (
            "كان بلا سعر إطلاقاً ('cannot be dispatched to your selected "
            "delivery location'). أي سعر يظهر هنا = التثبيت اشتغل."
        ),
    },
]


def line(ch="─", n=74):
    print(ch * n)


def show(product) -> dict:
    raw = getattr(product, "raw", {}) or {}
    fields = {
        "name": (getattr(product, "name", "") or "")[:58],
        "price": getattr(product, "price", None),
        "currency": getattr(product, "currency", None),
        "list_price": getattr(product, "list_price", None),
        "in_stock": getattr(product, "in_stock", None),
        "sku": getattr(product, "sku", None),
        "url": (getattr(product, "url", "") or "")[:70],
    }
    for key, value in fields.items():
        print(f"    {key:12s}: {value!r}")

    discount = None
    try:
        discount = product.discount_pct
        if callable(discount):
            discount = discount()
    except Exception:
        pass
    print(f"    {'discount_pct':12s}: {discount!r}")

    for key in ("market", "ship_to", "container", "price_source", "seller",
                "availability_text", "location_blocked", "unavailable_reason"):
        if key in raw:
            print(f"    raw.{key:9s}: {raw[key]!r}")
    return raw


def check(case, product, raw) -> list[str]:
    """يقارن بالمتوقع ويرجّع قائمة المشاكل."""
    problems = []
    price = getattr(product, "price", None)
    currency = getattr(product, "currency", None)

    if price is None:
        problems.append("ما فيه سعر إطلاقاً")
    if currency != case["currency"]:
        problems.append(f"العملة {currency!r} والمتوقع {case['currency']!r}")
    if raw.get("location_blocked"):
        problems.append(
            "location_blocked ما زال True بعد الاسترجاع -> تثبيت البلد فشل. "
            "لو عندك بروكسيات مفعّلة فهذا العرَض المتوقع: الـ POST خرج من IP "
            "والجلب التالي من IP ثانٍ"
        )
    if raw.get("ship_to") and raw.get("market"):
        pass
    if case["price"] is not None and price != case["price"]:
        problems.append(
            f"السعر {price} والمتوقع {case['price']} — إما الموقع غيّر سعره "
            "(افتح الصفحة وتأكد) وإما الاستخراج انكسر"
        )
    if case["list_price"] is not None:
        if getattr(product, "list_price", None) != case["list_price"]:
            problems.append(
                f"السعر المشطوب {product.list_price} والمتوقع {case['list_price']}"
            )
    if case["url"].endswith("B09WVVZQD3") and price == Decimal("314.89"):
        problems.append(
            "السعر 314.89 بالضبط = سعر التصدير للسعودية محوّلاً لليورو. "
            "يعني بلد التوصيل ما انثبت والعرض ما تغيّر"
        )
    return problems


def main():
    try:
        from productspy import get_product_info
    except Exception as exc:
        print(f"!! استيراد productspy فشل: {exc}")
        print("   شغّله من جذر المشروع مع تفعيل .venv")
        return

    print("توقيع الواجهة:", end=" ")
    try:
        print(f"get_product_info{inspect.signature(get_product_info)}")
    except Exception:
        print("(تعذّر)")

    verdicts = []
    for case in CASES:
        print()
        line("═")
        print(f"{case['label']}   {case['url']}")
        line("═")
        print(f"  ملاحظة: {case['note']}")

        product = None
        for attempt in (1, 2):
            started = time.time()
            try:
                product = get_product_info(case["url"])
                elapsed = time.time() - started
                tag = "الأولى (تدفع ثمن التثبيت)" if attempt == 1 else "الثانية (المفروض أسرع)"
                print(f"\n  ▸ المحاولة {attempt} — {tag}: {elapsed:.1f}ث")
            except Exception as exc:
                elapsed = time.time() - started
                print(f"\n  ▸ المحاولة {attempt}: انفجرت بعد {elapsed:.1f}ث")
                print(f"    {type(exc).__name__}: {str(exc)[:180]}")
                print("    BlockedError = أعد المحاولة/بدّل بروكسي")
                print("    ParseError   = الموقع غيّر تصميمه، المحددات لازم تتحدث")
                traceback.print_exc(limit=2)
                product = None
                break
            if attempt == 1:
                raw = show(product)

        if product is None:
            verdicts.append((case["label"], ["انفجر"]))
            continue

        problems = check(case, product, raw)
        if problems:
            print("\n  ✗ مشاكل:")
            for p in problems:
                print(f"      - {p}")
        else:
            print("\n  ✓ مطابق للمتوقع")
        verdicts.append((case["label"], problems))

    print()
    line("═")
    print("الخلاصة")
    line("═")
    for label, problems in verdicts:
        print(f"  {'✓' if not problems else '✗'}  {label}"
              + ("" if not problems else f"  ({len(problems)} مشكلة)"))
    print("\nالرقمان اللي يحتاجان عينك لا الكود: سعر ألمانيا وسعر بريطانيا.")
    print("افتح الرابطين في المتصفح وقارن الرقم المعروض بالمطبوع فوق.")


if __name__ == "__main__":
    main()