import re
import email
import html as html_lib
import numpy as np
import joblib
import streamlit as st
from email import policy


# ── Trusted sender domains ────────────────────────────────────────────────────
TRUSTED_DOMAINS = [
    # Malaysian services
    'mcdonalds.com', 'mcdelivery.com.my', 'mcdonalds.com.my',
    'maybank.com', 'maybank2u.com.my', 'cimb.com', 'cimbclicks.com.my',
    'rhbbank.com', 'publicbank.com.my', 'hlbank.com.my',
    'grabpay.com', 'grab.com', 'touchngo.com.my', 'tngdigital.com.my',
    'shopee.com.my', 'lazada.com.my', 'airasia.com', 'maxis.com.my',
    'celcom.com.my', 'digi.com.my', 'unifi.com.my', 'tm.com.my',
    'pos.com.my', 'poslaju.com.my',
    # Global services
    'google.com', 'youtube.com', 'microsoft.com', 'apple.com',
    'amazon.com', 'paypal.com', 'netflix.com', 'spotify.com',
    'linkedin.com', 'twitter.com', 'facebook.com', 'instagram.com',
    'github.com', 'stripe.com', 'visa.com', 'mastercard.com',
    'steampowered.com', 'fiuu.com',
]


# =============================================================================
# PREPROCESSING
# =============================================================================

def clean_email(text):
    if not isinstance(text, str):
        return ""
    text = text.lower()

    url_noise = {
        'http', 'https', 'www', 'com', 'net',
        'org', 'html', 'php', 'aspx', 'htm'
    }
    def replace_url(match):
        url    = match.group(0)
        domain = re.sub(r'https?://', '', url).split('/')[0]
        words  = re.sub(r'[^a-z\s]', ' ', domain)
        words  = ' '.join(
            w for w in words.split()
            if len(w) >= 4 and w not in url_noise  # ← add this
        )
        return f' urltoken {words} '

    text = re.sub(r'http\S+|www\S+', replace_url, text)
    text = re.sub(r'\S+@\S+',        ' emailtoken ', text)
    text = re.sub(r'[^a-z\s]',       ' ',            text)
    text = re.sub(r'\s+',            ' ',            text).strip()
    return text




def strip_html(html_text):
    """
    Strip HTML tags and decode entities to get clean readable text.
    Handles Outlook-style HTML emails with inline styles.
    """
    # Remove <style> and <script> blocks entirely
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', html_text,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text,
                  flags=re.DOTALL | re.IGNORECASE)

    # Remove inline style attributes
    text = re.sub(r'\s*style\s*=\s*["\'][^"\']*["\']', ' ', text,
                  flags=re.IGNORECASE)

    # Strip all remaining tag attributes, keep only tag names
    text = re.sub(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>', r'<\1>', text)

    # Replace block-level tags with newlines
    text = re.sub(r'<(br|p|div|tr|li|h[1-6])[^>]*>', '\n', text,
                  flags=re.IGNORECASE)

    # Remove all remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)

    # Decode HTML entities (&amp; &nbsp; etc.)
    text = html_lib.unescape(text)

    # Clean up whitespace
    text = re.sub(r'\n\s*\n', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def parse_eml(uploaded_file):
    """
    Extract plain text and metadata from a .eml file.
    Handles both plain text and HTML-only emails (e.g. from Outlook).

    Returns:
        subject       (str)  — email subject line
        body          (str)  — clean plain text body
        combined_text (str)  — subject + body used as ML input
        metadata      (dict) — sender, reply_to, date, subject
    """
    raw = uploaded_file.read()
    try:
        raw_str = raw.decode('utf-8', errors='ignore')
    except Exception:
        raw_str = raw.decode('latin-1', errors='ignore')

    msg = email.message_from_string(raw_str, policy=policy.default)

    subject  = msg.get('subject',  '') or ''
    sender   = msg.get('from',     '') or ''
    reply_to = msg.get('reply-to', '') or ''
    date     = msg.get('date',     '') or ''
    # ── new fields ──────────────────
    return_path =  msg.get('return-path',       '') or ''
    x_mailer =     msg.get('x-mailer',          '') or ''
    message_id =   msg.get('message-id',        '') or ''
    auth_results = msg.get('authentication-results', '') or ''


    plain_body = ''
    html_body  = ''

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == 'text/plain' and not plain_body:
                try:
                    plain_body = part.get_content()
                except Exception:
                    payload    = part.get_payload(decode=True)
                    plain_body = payload.decode('utf-8', errors='ignore') if payload else ''
            elif ctype == 'text/html' and not html_body:
                try:
                    html_body = part.get_content()
                except Exception:
                    payload   = part.get_payload(decode=True)
                    html_body = payload.decode('utf-8', errors='ignore') if payload else ''
    else:
        ctype = msg.get_content_type()
        try:
            content = msg.get_content()
        except Exception:
            payload = msg.get_payload(decode=True)
            content = payload.decode('utf-8', errors='ignore') if payload else ''

        if ctype == 'text/html':
            html_body = content
        else:
            plain_body = content

    if not plain_body and html_body:
        plain_body = strip_html(html_body)

    body = strip_html(plain_body).strip()
    combined_text = f"{subject} {body}"

    metadata = {
        'sender':   sender,
        'reply_to': reply_to,
        'date':     date,
        'subject':  subject,
        'return_path':  msg.get('return-path',       '') or '',
        'x_mailer':     msg.get('x-mailer',          '') or '',
        'message_id':   msg.get('message-id',        '') or '',
        'auth_results': msg.get('authentication-results', '') or ''
    }

    return subject, body, combined_text, metadata


def extract_urls(text):
    """Extract raw URLs from original email text before cleaning."""
    if not isinstance(text, str):
        return []
    pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$\-_@.&+!*\\(\\),]|'
        r'(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        r'|www\.[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}(?:/\S*)?',
        re.IGNORECASE
    )
    return pattern.findall(text)


def is_suspicious_url(url):
    """
    Basic rule-based URL suspicion checks.

    Returns:
        is_suspicious (bool)
        reasons       (list of str)
    """
    url_lower = url.lower()
    reasons   = []

    if re.search(r'http[s]?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', url_lower):
        reasons.append("uses an IP address instead of a domain name")

    suspicious_keywords = [
        'verify', 'secure', 'login', 'account', 'update', 'confirm',
        'banking', 'signin', 'password', 'credential', 'validate',
        'suspend', 'alert', 'urgent', 'free', 'winner', 'click'
    ]
    found_kw = [kw for kw in suspicious_keywords if kw in url_lower]
    if found_kw:
        reasons.append(f"contains suspicious words: {', '.join(found_kw[:3])}")

    try:
        domain = re.sub(r'https?://', '', url_lower).split('/')[0]
        if domain.count('.') >= 3:
            reasons.append("has an unusually long or complex domain")
    except Exception:
        pass

    legit_brands = [
        'paypal', 'maybank', 'cimb', 'google', 'microsoft',
        'apple', 'amazon', 'facebook', 'instagram', 'netflix'
    ]
    for brand in legit_brands:
        if brand in url_lower:
            domain = re.sub(r'https?://', '', url_lower).split('/')[0]
            if not domain.endswith(f'{brand}.com') and \
               not domain.endswith(f'{brand}.com.my'):
                reasons.append(
                    f"impersonates '{brand}' but is not their official domain"
                )
            break

    if url_lower.startswith('http://'):
        reasons.append("uses insecure HTTP instead of HTTPS")

    return len(reasons) > 0, reasons


# =============================================================================
# PREDICTION
# =============================================================================

@st.cache_resource
def load_model():
    """Load and cache the ML model and TF-IDF vectorizer."""
    model = joblib.load('model/logistic_model.pkl')
    tfidf = joblib.load('model/tfidf_vectorizer.pkl')
    return model, tfidf


def predict(clean_text, model, tfidf,strict=False):
    """
    Run prediction and apply threshold zone logic.

    Threshold zones:
        phishing_prob >= 0.70  → PHISHING
        phishing_prob <= 0.30  → LEGITIMATE
        between 0.30 - 0.70   → UNCERTAIN
    """

    vec           = tfidf.transform([clean_text])
    proba         = model.predict_proba(vec)[0]
    phishing_prob = proba[1]
    confidence    = max(proba) * 100

    high = 0.70 if strict else 0.80
    low  = 0.30 if strict else 0.35

    if phishing_prob >= high:
        verdict = "PHISHING"
    elif phishing_prob <= low:
        verdict = "LEGITIMATE"
    else:
        verdict = "UNCERTAIN"

    prediction = 1 if phishing_prob >= 0.50 else 0

    return verdict, phishing_prob, confidence, prediction


def get_explanation(clean_text, prediction, model, tfidf):
    """
    Core XAI function — maps TF-IDF weights × model coefficients to find
    the exact words that most influenced the classification decision.

    Returns:
        top_words  (list of str)
        top_scores (list of float)
    """
    feature_names = np.array(tfidf.get_feature_names_out())
    coefficients  = model.coef_[0]
    tfidf_vector  = tfidf.transform([clean_text])
    tfidf_scores  = tfidf_vector.toarray()[0]

    word_scores      = tfidf_scores * coefficients
    present_word_idx = np.where(tfidf_scores > 0)[0]

    if len(present_word_idx) == 0:
        return [], []

    if prediction == 1:
        top_idx = present_word_idx[
            np.argsort(word_scores[present_word_idx])[-8:][::-1]
        ]
    else:
        top_idx = present_word_idx[
            np.argsort(word_scores[present_word_idx])[:8]
        ]

    top_words  = [feature_names[i] for i in top_idx]
    top_scores = [abs(word_scores[i]) for i in top_idx]

    return top_words, top_scores


def check_trusted_sender(sender):
    """
    Check if sender email belongs to a known trusted domain.

    Returns:
        is_trusted    (bool)
        sender_domain (str)
    """
    if not sender:
        return False, ''

    sender_emails = re.findall(r'[\w\.-]+@[\w\.-]+', sender)
    if not sender_emails:
        return False, ''

    sender_domain = sender_emails[0].split('@')[-1].lower()

    for trusted in TRUSTED_DOMAINS:
        if sender_domain == trusted or sender_domain.endswith('.' + trusted):
            return True, sender_domain

    return False, sender_domain


def analyse_metadata(metadata):
    """
    Analyse email header metadata for phishing indicators.
    Runs independently of the ML model.

    Returns:
        warnings (list of str)
    """
    warnings = []
    sender   = metadata.get('sender',   '')
    reply_to = metadata.get('reply_to', '')
    subject  = metadata.get('subject',  '')

    # Sender vs Reply-To domain mismatch
    if sender and reply_to:
        sender_emails   = re.findall(r'[\w\.-]+@[\w\.-]+', sender)
        reply_to_emails = re.findall(r'[\w\.-]+@[\w\.-]+', reply_to)
        if sender_emails and reply_to_emails:
            s_domain  = sender_emails[0].split('@')[-1].lower()
            rt_domain = reply_to_emails[0].split('@')[-1].lower()
            if s_domain != rt_domain:
                warnings.append(
                    f"📨 **Sender/Reply-To mismatch** — Email claims to be from "
                    f"`{sender_emails[0]}` but replies go to `{reply_to_emails[0]}`. "
                    f"This is a common phishing tactic."
                )

    # Legit brand name sending from free email provider
    if sender:
        sender_emails = re.findall(r'[\w\.-]+@[\w\.-]+', sender)
        if sender_emails:
            sender_addr  = sender_emails[0].lower()
            domain       = sender_addr.split('@')[-1]
            free_domains = ['gmail.com', 'yahoo.com', 'hotmail.com',
                            'outlook.com', 'maktoob.com', 'spinfinder.com']
            brands       = ['maybank', 'cimb', 'paypal', 'google', 'microsoft',
                            'apple', 'amazon', 'facebook', 'netflix',
                            'university', 'bank']
            for brand in brands:
                if brand in sender.lower() and domain in free_domains:
                    warnings.append(
                        f"👤 **Suspicious sender** — Claims to be from a trusted "
                        f"organisation but uses a personal email `{domain}`."
                    )
                    break

            # Too many digits in local part
            local_part  = sender_addr.split('@')[0]
            digit_ratio = sum(c.isdigit() for c in local_part) / max(len(local_part), 1)
            if digit_ratio > 0.4 and len(local_part) > 6:
                warnings.append(
                    f"👤 **Unusual sender address** — `{sender_addr}` contains "
                    f"many numbers, unusual for official organisations."
                )

    # Urgent subject keywords
    if subject:
        urgent_words = ['urgent', 'immediate', 'action required', 'verify',
                        'suspended', 'locked', 'winner', 'congratulations',
                        'free', 'act now', 'expires']
        found = [w for w in urgent_words if w in subject.lower()]
        if found:
            warnings.append(
                f"📋 **Suspicious subject line** — Contains high-pressure "
                f"words: {', '.join(found)}."
            )
    # Return-Path vs Sender mismatch ─
    return_path = metadata.get('return_path', '')
    if return_path and sender:
        sender_emails      = re.findall(r'[\w\.-]+@[\w\.-]+', sender)
        return_path_emails = re.findall(r'[\w\.-]+@[\w\.-]+', return_path)
        if sender_emails and return_path_emails:
            s_domain  = sender_emails[0].split('@')[-1].lower()
            rp_domain = return_path_emails[0].split('@')[-1].lower()
            if s_domain != rp_domain:
                warnings.append(
                    f"↩️ **Return-Path mismatch** — Email is from `{s_domain}` "
                    f"but bounces go to `{rp_domain}`. "
                    f"This may indicate a spoofed sender."
                )

    # Suspicious X-Mailer (bulk email tools) ───────────────
    x_mailer = metadata.get('x_mailer', '').lower()
    bulk_mailers = ['sendgrid', 'mailchimp', 'constantcontact',
                    'massmailer', 'bulkmailer', 'phpmailer']
    for mailer in bulk_mailers:
        if mailer in x_mailer:
            warnings.append(
                f"📬 **Bulk mail tool detected** — This email was sent using "
                f"`{x_mailer}`, a bulk mailing service. "
                f"Legitimate personal emails rarely use these."
            )
            break

    # No Message-ID (forged or auto-generated spam) ────────
    message_id = metadata.get('message_id', '')
    if not message_id:
        warnings.append(
            "🔎 **Missing Message-ID** — Legitimate emails always have a "
            "unique Message-ID. Its absence may indicate a forged email."
        )

    # SPF / DKIM fail indicators in headers ────────────────
    auth_results = metadata.get('auth_results', '').lower()
    if 'spf=fail' in auth_results:
        warnings.append(
            "🛡️ **SPF check failed** — The sending server is not authorised "
            "to send emails on behalf of this domain. High phishing indicator."
        )
    if 'dkim=fail' in auth_results:
        warnings.append(
            "🛡️ **DKIM signature invalid** — The email's cryptographic "
            "signature is broken, suggesting it may have been tampered with."
        )

    return warnings


# =============================================================================
# EXPLANATION
# =============================================================================

def generate_plain_explanation(top_words, verdict, urls_found=None):
    """
    Convert ML output into plain English explanations for non-technical users.

    Returns:
        reasons (list of str)
    """
    if urls_found is None:
        urls_found = []

    if verdict == "PHISHING":
        reasons = []

        # URL analysis runs independently of keyword scores
        for url in urls_found[:3]:
            is_susp, url_reasons = is_suspicious_url(url)
            short_url = url[:60] + "..." if len(url) > 60 else url
            if is_susp:
                reasons.append(
                    f"🔗 **Suspicious link detected** — `{short_url}` — "
                    f"{'; '.join(url_reasons)}."
                )
            else:
                reasons.append(
                    f"🔗 **Link found** — `{short_url}` — "
                    f"Always verify links before clicking."
                )

        urgency_words    = {'urgent', 'immediately', 'suspended', 'verify',
                            'expire', 'alert', 'warning', 'act', 'now', 'hours'}
        financial_words  = {'bank', 'account', 'credit', 'payment', 'transfer',
                            'fund', 'money', 'wire', 'cash','rm'}
        credential_words = {'password', 'login', 'username', 'credential',
                            'confirm', 'validate', 'authentication'}
        link_words       = {'urltoken', 'click', 'link', 'http', 'www'}
        personal_words   = {'ssn', 'social', 'personal', 'information',
                            'provide', 'submit'}

        word_set = set(top_words)

        if word_set & urgency_words:
            reasons.append(
                "⚠️ **Urgent language detected** — The email uses pressure "
                "tactics like urgency or threats to rush your decision."
            )
        if word_set & financial_words:
            reasons.append(
                "💰 **Financial content detected** — The email mentions banking "
                "or financial information, a common phishing tactic."
            )
        if word_set & credential_words:
            reasons.append(
                "🔑 **Credential request detected** — The email asks you to "
                "confirm or provide login details."
            )
        if word_set & link_words:
            reasons.append(
                "🔗 **Suspicious link detected** — The email contains links "
                "that may redirect to a fake website."
            )
        if word_set & personal_words:
            reasons.append(
                "👤 **Personal information requested** — The email asks you "
                "to submit personal or sensitive information."
            )

        if not reasons:
            reasons.append(
                f"🚩 **Suspicious pattern detected** — Key terms found: "
                f"{', '.join(top_words[:5])}"
            )

        return reasons

    elif verdict == "LEGITIMATE":
        reasons = [
            "✅ **No suspicious patterns found** — The email uses normal, "
            "professional language with no phishing indicators."
        ]
        if urls_found:
            reasons.append(
                "🔗 **Note:** This email contains links. Always hover over "
                "links to verify the destination before clicking."
            )
        return reasons

    else:  # UNCERTAIN
        reasons = [
            "🔍 **Mixed signals detected** — This email contains some patterns "
            "found in phishing emails but also characteristics of legitimate emails. "
            "The system cannot make a confident decision."
        ]
        for url in urls_found[:3]:
            is_susp, url_reasons = is_suspicious_url(url)
            short_url = url[:60] + "..." if len(url) > 60 else url
            if is_susp:
                reasons.append(
                    f"🔗 **Suspicious link found** — `{short_url}` — "
                    f"{'; '.join(url_reasons)}."
                )
            else:
                reasons.append(
                    f"🔗 **Link found** — `{short_url}` — Verify before clicking."
                )
        return reasons


def highlight_text(original_text, suspicious_words):
    """
    Highlight suspicious words using a single regex pass.
    Single pass prevents injected HTML from being re-matched by later words.
    """
    safe_text = html_lib.escape(original_text)

    if not suspicious_words:
        return safe_text.replace('\n', '<br>')

    # Build ONE pattern that matches all words simultaneously
    pattern = re.compile(
        '|'.join(re.escape(w) for w in suspicious_words),
        re.IGNORECASE
    )

    safe_text = pattern.sub(
        lambda m: f'<mark class="highlight-suspicious">{m.group()}</mark>',
        safe_text
    )

    return safe_text.replace('\n', '<br>')
