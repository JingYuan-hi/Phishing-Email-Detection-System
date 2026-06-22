import streamlit as st
from utils import (
    load_model, parse_eml,
    clean_email, extract_urls,
    predict, get_explanation,
    check_trusted_sender, analyse_metadata,
    generate_plain_explanation, highlight_text,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Phishing Detector",
    page_icon="🛡️",
    layout="wide"
)

# ── Load CSS ──────────────────────────────────────────────────────────────────
with open('style.css', encoding='utf-8') as f:
    st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# ── Load model ────────────────────────────────────────────────────────────────
model, tfidf = load_model()

# ── Session state ─────────────────────────────────────────────────────────────
if 'clear_count' not in st.session_state:
    st.session_state.clear_count = 0

# ── Inject light theme class ──────────────────────────────────────────────────
st.markdown("""
<script>
    (function() {
        function applyTheme() {
            const app = window.parent.document.querySelector('.stApp');
            if (app) {
                app.classList.remove('theme-dark');
                app.classList.add('theme-light');
            } else {
                setTimeout(applyTheme, 50);
            }
        }
        applyTheme();
    })();
</script>
""", unsafe_allow_html=True)

# ── Guide dialog ──────────────────────────────────────────────────────────────
@st.dialog("How to export your email as .eml", width="large")
def show_guide():
    tab1, tab2 = st.tabs(["Gmail", "Outlook"])
    with tab1:
        st.markdown("""
        1. Open the email in Gmail
        2. Click the **three dots (⋮)** in the top-right corner
        3. Select **"Download message"**
        4. Upload the downloaded `.eml` file here
        """)
    with tab2:
        st.markdown("""
        1. Open the email in Outlook
        2. Go to **File → Save As**
        3. Choose format: **Outlook Message Format**
           or drag the email to your desktop to get a `.eml` file
        4. Upload the file here
        """)

# ── Header ────────────────────────────────────────────────────────────────────
title_col, guide_col = st.columns([5, 1])

with title_col:
    st.markdown(
        '<div class="app-header">'
        '<span class="app-title">Phishing Email Detector</span>'
        # '<span class="app-badge">AI-Powered</span>'
        '</div>',
        unsafe_allow_html=True
    )

with guide_col:
    st.markdown("<div style='padding-top:2px;'>", unsafe_allow_html=True)
    if st.button("Guide", key="guide_button", use_container_width=True):
        show_guide()
    st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# ── Two-column layout ─────────────────────────────────────────────────────────
col_input, col_output = st.columns([1, 1], gap="large")

# =============================================================================
# LEFT COLUMN — Input
# =============================================================================
with col_input:
    st.subheader("Email Input")

    input_method = st.radio(
        "Input method:",
        ["Paste text", "Upload .eml file"],
        horizontal=True,
        label_visibility="collapsed"
    )

    email_text   = ""
    display_text = ""
    metadata     = None
    uploaded     = None
    sender_hint  = ""
    is_eml       = False

    if input_method == "Paste text":
        display_text = st.text_area(
            "Email content",
            height=260,
            placeholder="Paste the email subject and body here...",
            key=f"email_input_{st.session_state.clear_count}",
            label_visibility="collapsed"
        )
        email_text = display_text

        sender_hint = st.text_input(
            "Sender address (optional — improves accuracy)",
            placeholder="e.g. noreply@microsoft.com",
            key=f"sender_hint_{st.session_state.clear_count}"
        )

    else:
        uploaded = st.file_uploader(
            "Upload .eml file",
            type=['eml'],
            key=f"eml_upload_{st.session_state.clear_count}",
            label_visibility="collapsed"
        )
        if uploaded:
            subject, body, email_text, metadata = parse_eml(uploaded)
            display_text = email_text
            st.success(f"Loaded: {uploaded.name}")

            with st.expander("Metadata"):
                if metadata['sender']:
                    st.markdown(f'<div class="meta-row"><span class="meta-key">From</span><span class="meta-val">{metadata["sender"]}</span></div>', unsafe_allow_html=True)
                if metadata['reply_to']:
                    st.markdown(f'<div class="meta-row"><span class="meta-key">Reply-To</span><span class="meta-val">{metadata["reply_to"]}</span></div>', unsafe_allow_html=True)
                if metadata['date']:
                    st.markdown(f'<div class="meta-row"><span class="meta-key">Date</span><span class="meta-val">{metadata["date"]}</span></div>', unsafe_allow_html=True)
                if metadata['subject']:
                    st.markdown(f'<div class="meta-row"><span class="meta-key">Subject</span><span class="meta-val">{metadata["subject"]}</span></div>', unsafe_allow_html=True)
                if metadata.get('auth_results'):
                    raw_auth = metadata["auth_results"].lower()
                    auth_badges = []
                    
                    # Search the messy string and extract only the pass/fail status
                    if "spf=pass" in raw_auth: auth_badges.append("SPF: Pass")
                    elif "spf=fail" in raw_auth: auth_badges.append("SPF: Fail")
                    
                    if "dkim=pass" in raw_auth: auth_badges.append("DKIM: Pass")
                    elif "dkim=fail" in raw_auth: auth_badges.append("DKIM: Fail")
                    
                    # Join them together nicely, or show a default message
                    clean_auth = " & ".join(auth_badges) if auth_badges else "None detected"
                    
                    st.markdown(f'<div class="meta-row"><span class="meta-key">Auth Checks</span><span class="meta-val">{clean_auth}</span></div>', unsafe_allow_html=True)

            with st.expander("Preview extracted text"):
                st.text(email_text)

    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        with st.container(key="clear_action"):
            clear = st.button("Clear", use_container_width=True)
    with btn_col2:
        with st.container(key="scan_action"):
            analyse = st.button("Scan email", type="primary", use_container_width=True)

    if clear:
        st.session_state.clear_count += 1
        st.rerun()

# =============================================================================
# RIGHT COLUMN — Result
# =============================================================================
with col_output:
    st.subheader("Scan Result")

    if not analyse:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-state-icon">◈</div>'
            '<div class="empty-state-text">Awaiting input</div>'
            '</div>',
            unsafe_allow_html=True
        )

    elif not email_text or len(email_text.strip()) < 10:
        st.error("No content to scan — paste an email or upload a .eml file.")

    else:
        with st.spinner("Scanning..."):

            urls_found = extract_urls(email_text)

            metadata_warnings = []
            is_trusted_sender = False
            is_authenticated  = False
            trusted_domain    = ''

            if input_method == "Upload .eml file" and uploaded and metadata:
                metadata_warnings = analyse_metadata(metadata)
                is_trusted_sender, trusted_domain = check_trusted_sender(
                    metadata.get('sender', '')
                )
            elif input_method == "Paste text" and sender_hint and sender_hint.strip():
                is_trusted_sender, trusted_domain = check_trusted_sender(sender_hint.strip())

            clean_text = clean_email(email_text)
            is_eml = (input_method == "Upload .eml file") and (uploaded is not None) and (metadata is not None)

            verdict, phishing_prob, confidence, prediction = predict(
                clean_text, model, tfidf, strict=is_eml
            )

            auth_results = metadata.get('auth_results', '').lower() if metadata else ""
            is_authenticated = ("spf=pass" in auth_results and "dkim=pass" in auth_results)

            if is_authenticated:
                if is_trusted_sender:
                    verdict = "LEGITIMATE"
                    phishing_prob = 0.23
                else:
                    if phishing_prob > 0.50:
                        phishing_prob -= 0.40
                        verdict = "LEGITIMATE" if phishing_prob < 0.35 else "UNCERTAIN"

            if verdict == "UNCERTAIN" and len(metadata_warnings) >= 2:
                verdict = "PHISHING"

            if verdict == "PHISHING":
                score_pct = f"{phishing_prob * 100:.1f}%"
                score_label = "phishing probability"
            elif verdict == "LEGITIMATE":
                score_pct = f"{(1 - phishing_prob) * 100:.1f}%"
                score_label = "safe probability"
            else:
                score_pct = f"{phishing_prob * 100:.1f}%"
                score_label = "uncertain — manual review advised"

            top_words, top_scores = get_explanation(clean_text, prediction, model, tfidf)
            INTERNAL_TOKENS = {'urltoken', 'emailtoken'}
            top_words = [w for w in top_words if len(w) >= 3 and w not in INTERNAL_TOKENS]

            plain_reasons = generate_plain_explanation(top_words, verdict, urls_found)

        # ── Verdict card ──────────────────────────────────────────
        if verdict == "PHISHING":
            card_class = "verdict-phishing"
            status_text = "Phishing detected"
        elif verdict == "LEGITIMATE":
            card_class = "verdict-legit"
            status_text = "No threat found"
        else:
            card_class = "verdict-uncertain"
            status_text = "Uncertain result"

        st.markdown(f"""
        <div class="verdict-card {card_class}">
            <div class="verdict-status">{status_text}</div>
            <div class="verdict-score">{score_pct}</div>
            <div class="verdict-label">{score_label}</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("")

        with st.expander("Explanation", expanded=False):
            for reason in plain_reasons:
                st.markdown(reason)
            if metadata_warnings:
                st.markdown("**Header analysis:**")
                for warning in metadata_warnings:
                    st.markdown(warning)

        if top_words and verdict in ["PHISHING", "UNCERTAIN"]:
            label = "Suspicious keywords" if verdict == "PHISHING" else "Flagged keywords"
            badge_class = "keyword-badge" if verdict == "PHISHING" else "keyword-badge-uncertain"
            with st.expander(label, expanded=False):
                badges = " ".join([
                    f'<span class="{badge_class}">{w}</span>'
                    for w in top_words
                ])
                st.markdown(badges, unsafe_allow_html=True)

        if display_text and top_words and verdict in ["PHISHING", "UNCERTAIN"]:
            st.markdown("**Annotated email:**")
            highlighted = highlight_text(display_text, top_words)
            st.markdown(
                f'<div class="email-preview">{highlighted}</div>',
                unsafe_allow_html=True
            )

        st.markdown("")
        if verdict == "PHISHING":
            st.error(
                "Do not click any links or share personal information. "
                "Delete this email or report it as phishing to your provider."
            )
        elif verdict == "LEGITIMATE":
            st.info(
                "This email appears safe. No suspicious patterns detected. "
                "No automated system is 100% accurate — stay alert."
            )
        else:
            st.warning(
                "The scanner cannot confidently classify this email. "
                "Check the sender's address carefully, avoid clicking links, "
                "and verify directly with the organisation if in doubt."
            )
