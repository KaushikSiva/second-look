// Second Look — content script.
// Scrapes the current product page into a Product object (see SPEC.md) and pushes it
// to the extension whenever it changes (initial load, late-loading prices, SPA URL changes).
(() => {
  'use strict';

  const alive = () => {
    try { return !!(chrome.runtime && chrome.runtime.id); } catch (_) { return false; }
  };
  // Guard against double injection (manifest + chrome.scripting fallback). If a previous
  // copy is orphaned (extension reloaded), its alive() returns false and we take over.
  if (window.__secondLook && typeof window.__secondLook.alive === 'function' && window.__secondLook.alive()) return;
  window.__secondLook = { alive };

  // ---------- helpers ----------
  const clean = (s) => (s == null ? '' : String(s)).replace(/[‎‏ ]/g, ' ').replace(/\s+/g, ' ').trim();
  const q = (sel, root = document) => { try { return root.querySelector(sel); } catch (_) { return null; } };
  const qa = (sel, root = document) => { try { return Array.from(root.querySelectorAll(sel)); } catch (_) { return []; } };
  const txt = (sel, root) => { const e = q(sel, root); return e ? clean(e.textContent) : ''; };
  const firstText = (sels) => { for (const s of sels) { const t = txt(s); if (t) return t; } return ''; };
  const meta = (name) => {
    const e = q(`meta[property="${name}"]`) || q(`meta[name="${name}"]`) || q(`meta[itemprop="${name}"]`);
    return e ? clean(e.getAttribute('content')) : '';
  };
  const truncate = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s);

  function parsePrice(v) {
    if (v == null || v === '') return null;
    if (typeof v === 'number') return isFinite(v) ? v : null;
    const s = clean(v);
    const m = s.match(/\d[\d.,\s]*/);
    if (!m) return null;
    let n = m[0].trim().replace(/\s/g, '');
    if (/,\d{1,2}$/.test(n) && !/\.\d{1,2}$/.test(n)) n = n.replace(/\./g, '').replace(',', '.'); // 1.299,99
    else n = n.replace(/,/g, '');
    n = n.replace(/\.$/, '');
    const f = parseFloat(n);
    return isFinite(f) ? Math.round(f * 100) / 100 : null;
  }

  function currencyOf(s, fallback = 'USD') {
    s = String(s || '');
    if (/CA\$|C\$|CAD/.test(s)) return 'CAD';
    if (/A\$|AUD/.test(s)) return 'AUD';
    if (/€|EUR/.test(s)) return 'EUR';
    if (/£|GBP/.test(s)) return 'GBP';
    if (/₹|INR/.test(s)) return 'INR';
    if (/¥|JPY/.test(s)) return 'JPY';
    if (/\$|USD/.test(s)) return 'USD';
    return fallback;
  }

  const parseRating = (s) => {
    const m = clean(s).match(/(\d+(?:[.,]\d+)?)\s*(?:out of|\/|of)\s*5/i) || clean(s).match(/^(\d(?:[.,]\d+)?)/);
    if (!m) return null;
    const f = parseFloat(m[1].replace(',', '.'));
    return isFinite(f) && f <= 5 ? f : null;
  };
  const parseCount = (s) => {
    const m = clean(s).match(/(\d[\d,.]*)\s*([kK])?/);
    if (!m) return null;
    let n = parseInt(m[1].replace(/[,.]/g, ''), 10);
    if (m[2]) n = Math.round(parseFloat(m[1].replace(/,/g, '')) * 1000);
    return isFinite(n) ? n : null;
  };
  const site = () => location.hostname.replace(/^www\.|^smile\./, '');

  function compact(obj) {
    const out = {};
    for (const [k, v] of Object.entries(obj)) {
      if (v == null || v === '' || (Array.isArray(v) && v.length === 0)) continue;
      out[k] = v;
    }
    return out;
  }

  // ---------- Amazon ----------
  function amazonAsin() {
    const m = location.pathname.match(/\/(?:dp|gp\/product|gp\/aw\/d|product-reviews|exec\/obidos\/ASIN)\/([A-Z0-9]{10})(?:[/?]|$)/i);
    if (m) return m[1].toUpperCase();
    const inp = q('input#ASIN') || q('input[name="ASIN"]');
    if (inp && inp.value) return inp.value.trim();
    const d = q('[data-asin]#dp') || q('#averageCustomerReviews[data-asin]');
    return d ? d.getAttribute('data-asin') : null;
  }

  function amazonImage() {
    const img = q('#landingImage') || q('#imgBlkFront') || q('#ebooksImgBlkFront') || q('#main-image') || q('#imgTagWrapperId img');
    if (!img) return meta('og:image') || null;
    const hires = img.getAttribute('data-old-hires');
    if (hires) return hires;
    const dyn = img.getAttribute('data-a-dynamic-image');
    if (dyn) {
      try {
        const entries = Object.entries(JSON.parse(dyn));
        entries.sort((a, b) => (b[1][0] * b[1][1]) - (a[1][0] * a[1][1]));
        if (entries[0]) return entries[0][0];
      } catch (_) { /* ignore */ }
    }
    return img.currentSrc || img.src || null;
  }

  function amazonDetails() {
    // Collect label → value pairs from the various product-details layouts.
    const pairs = [];
    const tables = '#productDetails_techSpec_section_1 tr, #productDetails_techSpec_section_2 tr, #productDetails_detailBullets_sections1 tr, .prodDetTable tr, #productOverview_feature_div tr, #technicalSpecifications_section_1 tr, #tech-specs-desktop tr';
    for (const tr of qa(tables)) {
      const cells = tr.querySelectorAll('th, td');
      if (cells.length >= 2) pairs.push([clean(cells[0].textContent), clean(cells[cells.length - 1].textContent)]);
    }
    for (const li of qa('#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li')) {
      const label = li.querySelector('.a-text-bold');
      if (!label) continue;
      const l = clean(label.textContent).replace(/[:‏‎]+/g, '').trim();
      const v = clean(li.textContent.replace(label.textContent, '')).replace(/^[:\s]+/, '');
      pairs.push([l, v]);
    }
    return pairs;
  }

  function amazonModel(pairs) {
    const pref = [/^item model number/i, /^model number/i, /^model$/i, /^part number/i, /^model name/i];
    for (const re of pref) {
      const hit = pairs.find(([l, v]) => re.test(l) && v && v.length < 80);
      if (hit) return hit[1];
    }
    return txt('.po-model_name td:last-child') || null;
  }

  function amazonBrand(pairs) {
    const po = txt('.po-brand td:last-child');
    if (po) return po;
    let b = txt('#bylineInfo');
    if (b) {
      b = b.replace(/^Visit the\s+/i, '').replace(/\s+Store$/i, '').replace(/^Brand:\s*/i, '');
      if (b && b.length < 60) return b;
    }
    const hit = pairs.find(([l]) => /^(brand|manufacturer)$/i.test(l));
    return hit ? hit[1] : null;
  }

  function amazonCoupon() {
    const sels = [
      '#couponBadgeRegularVpc', '[id^="couponText"]', '#couponText', '.couponLabelText', '#vpcButton',
      '#promoPriceBlockMessage_feature_div', '#couponFeature', '#coupons_feature_div',
      '#applicable_promotion_list_sec', '#dealBadge_feature_div', '#snsDetailPagePrice'
    ];
    for (const s of sels) {
      for (const e of qa(s)) {
        const t = clean(e.textContent);
        if (!t) continue;
        const m = t.match(/(apply|clip|save|extra)[^.]{0,60}?(coupon|\d+%(\s*(off|coupon))?|\$\s?\d[\d.,]*(\s*(off|coupon))?)/i);
        if (m) return truncate(clean(m[0]), 120);
      }
    }
    return null;
  }

  function amazonPrice() {
    const sels = [
      '#corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen',
      '#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen',
      '#corePriceDisplay_desktop_feature_div .a-price:not(.a-text-price) .a-offscreen',
      '#corePrice_desktop .a-price:not(.a-text-price) .a-offscreen',
      '#apex_desktop .priceToPay .a-offscreen',
      '#apex_desktop .a-price:not(.a-text-price) .a-offscreen',
      '#priceblock_dealprice', '#priceblock_ourprice', '#priceblock_saleprice',
      '#price_inside_buybox', '#newBuyBoxPrice', '#tp_price_block_total_price_ww .a-offscreen',
      '#kindle-price', '#price', '.a-price.priceToPay .a-offscreen',
      '#buybox .a-price .a-offscreen', '#centerCol .a-price .a-offscreen'
    ];
    for (const s of sels) {
      const e = q(s);
      const t = e && clean(e.textContent);
      if (t && parsePrice(t) != null) return t;
    }
    // Split whole/fraction rendering when .a-offscreen is empty
    const root = q('#corePriceDisplay_desktop_feature_div') || q('#corePrice_feature_div') || q('#apex_desktop') || document;
    const whole = txt('.a-price-whole', root);
    if (whole) {
      const frac = txt('.a-price-fraction', root) || '00';
      const sym = txt('.a-price-symbol', root) || '$';
      return `${sym}${whole.replace(/[.,]$/, '')}.${frac}`;
    }
    return '';
  }

  function amazonListPrice(price) {
    const sels = [
      '#corePriceDisplay_desktop_feature_div .basisPrice .a-offscreen',
      '#corePrice_feature_div .a-text-price .a-offscreen',
      '#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen',
      '#corePrice_desktop .a-text-price .a-offscreen',
      '#apex_desktop .a-text-price .a-offscreen',
      '.basisPrice .a-offscreen', '#priceblock_listprice', '#listPrice', '.priceBlockStrikePriceString'
    ];
    for (const s of sels) {
      const v = parsePrice(txt(s));
      if (v != null && (price == null || v > price)) return v;
    }
    return null;
  }

  function amazon() {
    const title = txt('#productTitle') || txt('#title') || txt('#ebooksProductTitle');
    if (!title) return null;
    const asin = amazonAsin();
    const priceText = amazonPrice();
    const price = parsePrice(priceText);
    const pairs = amazonDetails();

    let rating = null;
    const pop = q('#acrPopover');
    if (pop) rating = parseRating(pop.getAttribute('title') || '') ?? parseRating(txt('.a-icon-alt', pop)) ?? parseRating(txt('.a-size-base', pop));
    if (rating == null) rating = parseRating(txt('#averageCustomerReviews .a-icon-alt') || txt('[data-hook="rating-out-of-text"]'));

    const reviewCount = parseCount(txt('#acrCustomerReviewText') || txt('[data-hook="total-review-count"]'));

    const bullets = qa('#feature-bullets li span.a-list-item, #feature-bullets li')
      .map((e) => clean(e.textContent))
      .filter((t, i, arr) => t && t.length > 3 && !/^make sure this fits/i.test(t) && arr.indexOf(t) === i)
      .slice(0, 8)
      .map((t) => truncate(t, 300));

    const reviewSnippets = qa('[data-hook="review-body"], [data-hook="review-collapsed"]')
      .map((e) => clean(e.textContent).replace(/\s*Read more\s*$/i, ''))
      .filter((t, i, arr) => t.length > 10 && arr.indexOf(t) === i)
      .slice(0, 8)
      .map((t) => truncate(t, 500));

    const url = asin ? `${location.origin}/dp/${asin}` : location.href.split('#')[0];

    return compact({
      url,
      site: site(),
      asin,
      title: truncate(title, 300),
      brand: amazonBrand(pairs),
      price,
      currency: currencyOf(priceText),
      list_price: amazonListPrice(price),
      rating,
      review_count: reviewCount,
      image: amazonImage(),
      model: amazonModel(pairs),
      bullets,
      review_snippets: reviewSnippets,
      coupon: amazonCoupon()
    });
  }

  // ---------- JSON-LD / microdata / OpenGraph (Best Buy, Walmart, Target, generic) ----------
  function ldProducts() {
    const found = [];
    const isProduct = (t) => (Array.isArray(t) ? t : [t]).some((x) => /^(Product|ProductGroup|IndividualProduct|ProductModel)$/i.test(String(x || '').replace(/^.*[/#]/, '')));
    const walk = (o, depth = 0) => {
      if (!o || typeof o !== 'object' || depth > 6) return;
      if (Array.isArray(o)) { o.forEach((x) => walk(x, depth + 1)); return; }
      if (isProduct(o['@type'])) found.push(o);
      if (o['@graph']) walk(o['@graph'], depth + 1);
      if (o.mainEntity) walk(o.mainEntity, depth + 1);
      if (o.itemListElement && depth < 2) walk(o.itemListElement, depth + 1);
    };
    for (const s of qa('script[type="application/ld+json"]')) {
      try { walk(JSON.parse(s.textContent.trim())); } catch (_) { /* malformed JSON-LD is common */ }
    }
    return found;
  }

  function ldOffer(p) {
    let offers = p.offers;
    if (!offers && Array.isArray(p.hasVariant)) {
      const v = p.hasVariant.find((x) => x && x.offers);
      offers = v && v.offers;
    }
    if (!offers) return {};
    const list = Array.isArray(offers) ? offers : [offers];
    for (const o of list) {
      if (!o) continue;
      const inner = Array.isArray(o.offers) ? o.offers[0] : null;
      const spec = Array.isArray(o.priceSpecification) ? o.priceSpecification[0] : o.priceSpecification;
      const price = parsePrice(o.price ?? o.lowPrice ?? (spec && spec.price) ?? (inner && inner.price));
      if (price != null) {
        return {
          price,
          currency: o.priceCurrency || (spec && spec.priceCurrency) || (inner && inner.priceCurrency) || null,
          high: parsePrice(o.highPrice)
        };
      }
    }
    return {};
  }

  const ldImage = (img) => {
    if (!img) return null;
    if (typeof img === 'string') return img;
    if (Array.isArray(img)) return ldImage(img[0]);
    return img.url || img.contentUrl || null;
  };
  const ldBrand = (b) => {
    if (!b) return null;
    if (typeof b === 'string') return b;
    if (Array.isArray(b)) return ldBrand(b[0]);
    return b.name || null;
  };

  function domPrice() {
    const sels = [
      // Best Buy
      '[data-testid="customer-price"] span', '.priceView-customer-price span', '.priceView-hero-price span',
      // Walmart
      '[itemprop="price"]', '[data-testid="price-wrap"] [itemprop="price"]', '[data-seo-id="hero-price"]',
      // Target
      '[data-test="product-price"]',
      // generic
      '.price .amount', '.product-price', '.price'
    ];
    for (const s of sels) {
      const e = q(s);
      if (!e) continue;
      const c = e.getAttribute('content');
      const t = c || clean(e.textContent);
      if (t && parsePrice(t) != null) return t;
    }
    return '';
  }

  function generic() {
    const lds = ldProducts();
    const p = lds.find((x) => x.offers) || lds[0] || null;
    const offer = p ? ldOffer(p) : {};
    const metaPrice = meta('product:price:amount') || meta('og:price:amount');
    const domP = offer.price == null && !metaPrice ? domPrice() : '';
    const price = offer.price ?? parsePrice(metaPrice) ?? parsePrice(domP);

    const title = clean((p && p.name) || meta('og:title') || txt('h1'));
    // Only claim a product when there is real product evidence.
    if (!title || (!p && price == null)) return null;

    const agg = p && p.aggregateRating;
    const reviews = p ? (Array.isArray(p.review) ? p.review : p.review ? [p.review] : []) : [];
    const domReviews = qa('[itemprop="reviewBody"], [data-testid="review-text"], .ugc-review-body, [data-test="review-card--text"]')
      .map((e) => clean(e.textContent));
    const snippets = reviews.map((r) => clean(r && (r.reviewBody || r.description)))
      .concat(domReviews)
      .filter((t, i, arr) => t && t.length > 10 && arr.indexOf(t) === i)
      .slice(0, 8)
      .map((t) => truncate(t, 500));

    let bullets = [];
    if (p && p.description) {
      bullets = clean(String(p.description).replace(/<[^>]+>/g, ' '))
        .split(/(?<=[.!?])\s+|\s•\s/)
        .map(clean).filter((s) => s.length > 15).slice(0, 6).map((t) => truncate(t, 300));
    }

    return compact({
      url: location.href.split('#')[0],
      site: site(),
      title: truncate(title, 300),
      brand: p ? ldBrand(p.brand) || ldBrand(p.manufacturer) : null,
      price,
      currency: offer.currency || meta('product:price:currency') || currencyOf(domP || metaPrice),
      rating: agg ? parsePrice(agg.ratingValue) : null,
      review_count: agg ? parseCount(String(agg.reviewCount ?? agg.ratingCount ?? '')) : null,
      image: (p && ldImage(p.image)) || meta('og:image') || null,
      model: p ? clean(p.model && typeof p.model === 'object' ? p.model.name : p.model) || clean(p.mpn) || clean(p.sku) || null : null,
      bullets,
      review_snippets: snippets
    });
  }

  function extract() {
    if (/(^|\.)amazon\./i.test(location.hostname)) {
      const a = amazon();
      if (a) return a;
    }
    return generic();
  }

  // ---------- messaging ----------
  let lastKey = '';
  let timer = null;

  function stop() { if (timer) clearInterval(timer); timer = null; }

  function push(force) {
    if (!alive()) { stop(); return; }
    let p = null;
    try { p = extract(); } catch (e) { p = null; }
    const k = p
      ? JSON.stringify([p.url, p.title, p.price, p.list_price, p.rating, p.review_count, p.coupon, p.image, (p.review_snippets || []).length])
      : 'none:' + location.href;
    if (!force && k === lastKey) return;
    lastKey = k;
    try {
      const r = chrome.runtime.sendMessage({ type: 'sl:product', product: p, url: location.href });
      if (r && typeof r.catch === 'function') r.catch(() => {});
    } catch (_) { stop(); }
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === 'sl:getProduct') {
      let p = null;
      try { p = extract(); } catch (_) { p = null; }
      sendResponse({ product: p, url: location.href });
    }
  });

  // Initial + late-loading content, then poll for SPA URL / DOM changes (cheap; dedup by key).
  push(true);
  setTimeout(() => push(false), 1200);
  setTimeout(() => push(false), 3500);
  timer = setInterval(() => push(false), 1500);
  window.addEventListener('popstate', () => setTimeout(() => push(false), 400));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) push(false); });
})();
