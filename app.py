import streamlit as st
import fitz
import re
import requests
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="PaperRenamer", layout="wide")

PASSWORD = "0210"

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 PaperRenamer 로그인")
    password = st.text_input("비밀번호를 입력하세요", type="password")

    if st.button("입장하기"):
        if password == PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")

    st.stop()

st.title("📚 PaperRenamer")
st.write("PDF 또는 ZIP 파일을 업로드한 뒤 [변경하기] 버튼을 누르면 자동 정리됩니다.")

st.markdown("""
<style>
.link-button {
    display: inline-block;
    padding: 10px 18px;
    margin: 6px;
    background-color: #f0f2f6;
    border-radius: 10px;
    text-decoration: none;
    color: black !important;
    font-weight: 600;
}
.link-button:hover {
    background-color: #dbe4ff;
}
</style>

### 🔗 논문 검색 바로가기

<a class="link-button" href="https://library.cnu.ac.kr/" target="_blank">📚 충남대학교 도서관</a>
<a class="link-button" href="https://scholar.google.com/" target="_blank">🔎 Google Scholar</a>
<a class="link-button" href="https://search.crossref.org/" target="_blank">🧷 Crossref DOI 검색</a>
<a class="link-button" href="https://pubmed.ncbi.nlm.nih.gov/" target="_blank">🧬 PubMed</a>
<a class="link-button" href="https://www.riss.kr/" target="_blank">📄 RISS</a>
<a class="link-button" href="https://www.dbpia.co.kr/" target="_blank">📘 DBpia</a>
<a class="link-button" href="https://kiss.kstudy.com/" target="_blank">📗 KISS</a>
<a class="link-button" href="https://www.google.com/" target="_blank">🌐 Chrome 새 탭 열기</a>
<a class="link-button" href="https://sci-hub.kr/" target="_blank">🔎 Sci-Hub</a>
""", unsafe_allow_html=True)

st.info("""
📌 논문 파일명 정리 규칙

[기본 스타일]
- 저자 1명: 저자, 연도. 논문제목앞부분.pdf
- 저자 2명: 저자 & 저자, 연도. 논문제목앞부분.pdf
- 저자 3명 이상: 저자 et al., 연도. 논문제목앞부분.pdf

[교수님 스타일]
- 저자_년도_핵심키워드.pdf
- 저자&저자_년도_핵심키워드.pdf
- 저자 et al_년도_핵심키워드.pdf

[APA 스타일]
- 국문: 학회지명 + 권(volume) 굵게
- 해외: 저널명 + 권(volume) 이탤릭체
""")

uploaded_files = st.file_uploader(
    "PDF 또는 ZIP 파일 업로드",
    type=["pdf", "zip"],
    accept_multiple_files=True
)

start_button = st.button("🚀 변경하기")


def clean_filename(text):
    invalid_chars = '\\/:*?"<>|'
    for ch in invalid_chars:
        text = text.replace(ch, "")
    return re.sub(r"\s+", " ", text).strip()


def expand_uploaded_files(uploaded_files):
    expanded_files = []

    for uploaded_file in uploaded_files:
        file_name = uploaded_file.name
        file_bytes = uploaded_file.read()

        if file_name.lower().endswith(".pdf"):
            expanded_files.append({
                "name": file_name,
                "bytes": file_bytes,
                "source": "PDF 직접 업로드"
            })

        elif file_name.lower().endswith(".zip"):
            try:
                zip_buffer = io.BytesIO(file_bytes)

                with zipfile.ZipFile(zip_buffer, "r") as zip_ref:
                    for zip_info in zip_ref.infolist():
                        if zip_info.is_dir():
                            continue

                        if zip_info.filename.lower().endswith(".pdf"):
                            pdf_bytes = zip_ref.read(zip_info.filename)
                            pdf_name = zip_info.filename.split("/")[-1]

                            expanded_files.append({
                                "name": pdf_name,
                                "bytes": pdf_bytes,
                                "source": f"ZIP 내부 파일: {file_name}"
                            })

            except zipfile.BadZipFile:
                st.error(f"ZIP 파일을 읽을 수 없습니다: {file_name}")

    return expanded_files


def is_korean_paper(info):
    target_text = (
        info.get("title", "") +
        info.get("journal", "") +
        " ".join([a.get("family", "") for a in info.get("authors", [])])
    )
    return bool(re.search(r"[가-힣]", target_text))


def find_doi(text):
    cleaned_text = text.replace("\n", " ").replace("\r", " ")
    cleaned_text = re.sub(r"\s+", " ", cleaned_text)

    doi_patterns = [
        r"https?://doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
        r"doi[:\s]*(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
        r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)"
    ]

    for pattern in doi_patterns:
        match = re.search(pattern, cleaned_text, re.I)
        if match:
            doi = match.group(1) if match.lastindex else match.group(0)
            return doi.rstrip(".,;)")

    return None


def extract_possible_titles(text, max_titles=5):
    lines = text.split("\n")
    candidates = []

    for line in lines:
        line = line.strip()

        if len(line) < 20:
            continue
        if len(line.split()) > 35:
            continue
        if "doi" in line.lower():
            continue
        if re.search(r"10\.\d", line):
            continue
        if re.search(r"^(abstract|keywords|introduction|references)$", line.lower()):
            continue
        if re.search(r"^\d+$", line):
            continue

        candidates.append(line)

    return candidates[:max_titles]


def get_crossref_info(doi):
    url = f"https://api.crossref.org/works/{doi}"
    response = requests.get(url, timeout=10)

    if response.status_code != 200:
        return None

    data = response.json()["message"]
    title = data.get("title", [""])[0]

    year = ""
    for key in ["published-print", "published-online", "published", "created"]:
        if key in data:
            year = data[key]["date-parts"][0][0]
            break

    authors = []
    for author in data.get("author", []):
        authors.append({
            "family": author.get("family", ""),
            "given": author.get("given", "")
        })

    journal = data.get("container-title", [""])[0] if data.get("container-title") else ""

    return {
        "title": title,
        "year": str(year),
        "authors": authors,
        "journal": journal,
        "volume": data.get("volume", ""),
        "issue": data.get("issue", ""),
        "page": data.get("page", ""),
        "doi": doi
    }


def get_crossref_info_by_title(title):
    url = "https://api.crossref.org/works"
    params = {
        "query.title": title,
        "rows": 3
    }

    response = requests.get(url, params=params, timeout=10)

    if response.status_code != 200:
        return None

    items = response.json()["message"]["items"]

    if not items:
        return None

    for item in items:
        doi = item.get("DOI", "")
        if doi:
            info = get_crossref_info(doi)
            if info:
                return info

    return None


def read_pdf_text_from_bytes(pdf_bytes):
    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")

    text = ""

    for page_num in range(min(8, len(pdf))):
        text += pdf[page_num].get_text()

    return text


def make_short_title(title, word_count=5):
    return clean_filename(" ".join(title.split()[:word_count]))


def make_author_filename_text(authors):
    last_names = [a["family"] for a in authors if a.get("family")]

    if len(last_names) == 0:
        return "Unknown"
    elif len(last_names) == 1:
        return last_names[0]
    elif len(last_names) == 2:
        return f"{last_names[0]} & {last_names[1]}"
    else:
        return f"{last_names[0]} et al."


def make_default_filename(info):
    return clean_filename(
        f"{make_author_filename_text(info['authors'])}, {info['year']}. {make_short_title(info['title'], 5)}.pdf"
    )


def make_professor_filename(info):
    last_names = [a["family"] for a in info["authors"] if a.get("family")]

    if len(last_names) == 0:
        author_text = "Unknown"
    elif len(last_names) == 1:
        author_text = last_names[0]
    elif len(last_names) == 2:
        author_text = f"{last_names[0]}&{last_names[1]}"
    else:
        author_text = f"{last_names[0]} et al"

    keyword = make_short_title(info["title"], 3).replace(" ", "_")
    return clean_filename(f"{author_text}_{info['year']}_{keyword}.pdf")


def make_initials(given):
    if not given:
        return ""
    parts = given.replace("-", " ").split()
    return " ".join([p[0].upper() + "." for p in parts if p])


def make_apa_plain(info):
    author_parts = []

    for author in info["authors"]:
        family = author.get("family", "")
        given = author.get("given", "")
        initials = make_initials(given)
        author_parts.append(f"{family}, {initials}".strip())

    if len(author_parts) == 0:
        author_text = "Unknown"
    elif len(author_parts) == 1:
        author_text = author_parts[0]
    elif len(author_parts) == 2:
        author_text = f"{author_parts[0]} & {author_parts[1]}"
    else:
        author_text = ", ".join(author_parts[:-1]) + f", & {author_parts[-1]}"

    issue_text = f"({info['issue']})" if info["issue"] else ""
    page_text = f", {info['page']}" if info["page"] else ""
    doi_text = f" https://doi.org/{info['doi']}" if info["doi"] else ""

    return (
        f"{author_text} ({info['year']}). "
        f"{info['title']}. "
        f"{info['journal']}, "
        f"{info['volume']}{issue_text}{page_text}."
        f"{doi_text}"
    ).strip()


def make_apa_markdown(info):
    apa = make_apa_plain(info)

    journal = info["journal"]
    volume = info["volume"]

    if is_korean_paper(info):
        if journal:
            apa = apa.replace(journal, f"**{journal}**", 1)
        if volume:
            apa = apa.replace(f", {volume}", f", **{volume}**", 1)
    else:
        if journal and volume:
            apa = apa.replace(f"{journal}, {volume}", f"*{journal}, {volume}*", 1)

    return apa


def make_apa_format_note(info):
    journal = info["journal"]
    volume = info["volume"]

    if is_korean_paper(info):
        return f"국문 논문으로 분류됨: 학회지명 '{journal}'과 권(volume) '{volume}'은 굵게 처리하세요. 쉼표는 굵게 처리하지 않습니다."
    else:
        return f"해외 논문으로 분류됨: 저널명 '{journal}'과 권(volume) '{volume}'은 이탤릭체로 처리하세요. 호(issue)는 이탤릭체로 처리하지 않습니다."


def make_search_links(info):
    title = info.get("title", "")
    doi = info.get("doi", "")

    scholar_url = f"https://scholar.google.com/scholar?q={requests.utils.quote(title)}"
    crossref_url = f"https://search.crossref.org/?q={requests.utils.quote(title)}"
    cnu_url = f"https://library.cnu.ac.kr/search/tot/result?st=KWRD&si=TOTAL&q={requests.utils.quote(title)}"
    doi_url = f"https://doi.org/{doi}" if doi else ""

    links = ""

    if doi_url:
        links += f'<a class="link-button" href="{doi_url}" target="_blank">🔗 DOI 바로가기</a>'

    links += f"""
    <a class="link-button" href="{scholar_url}" target="_blank">🔎 Google Scholar 검색</a>
    <a class="link-button" href="{crossref_url}" target="_blank">🧷 Crossref 검색</a>
    <a class="link-button" href="{cnu_url}" target="_blank">📚 충남대 도서관 검색</a>
    """

    return links


if uploaded_files and not start_button:
    st.warning("파일 업로드가 완료되었습니다. 정리를 시작하려면 [🚀 변경하기] 버튼을 눌러주세요.")


if uploaded_files and start_button:
    expanded_files = expand_uploaded_files(uploaded_files)

    if not expanded_files:
        st.error("처리할 PDF 파일이 없습니다. PDF 또는 PDF가 들어 있는 ZIP 파일을 업로드해주세요.")
        st.stop()

    results = []
    pdf_files_for_zip = []

    progress_bar = st.progress(0)
    status_text = st.empty()

    total_files = len(expanded_files)

    for idx, file_item in enumerate(expanded_files, start=1):
        original_name = file_item["name"]
        pdf_bytes = file_item["bytes"]
        source = file_item["source"]

        status_text.write(f"처리 중: {idx} / {total_files} - {original_name}")

        try:
            text = read_pdf_text_from_bytes(pdf_bytes)

            doi = find_doi(text)
            info = get_crossref_info(doi) if doi else None

            if not info:
                possible_titles = extract_possible_titles(text)

                for possible_title in possible_titles:
                    info = get_crossref_info_by_title(possible_title)
                    if info:
                        break

            if not info:
                results.append({
                    "원래 파일명": original_name,
                    "업로드 출처": source,
                    "논문 구분": "",
                    "상태": "자동 정리 실패"
                })
                progress_bar.progress(idx / total_files)
                continue

            paper_type = "국문" if is_korean_paper(info) else "해외"

            default_filename = make_default_filename(info)
            professor_filename = make_professor_filename(info)

            results.append({
                "원래 파일명": original_name,
                "업로드 출처": source,
                "논문 구분": paper_type,
                "저자": make_author_filename_text(info["authors"]),
                "연도": info["year"],
                "제목": info["title"],
                "저널/학회지": info["journal"],
                "권": info["volume"],
                "호": info["issue"],
                "페이지": info["page"],
                "DOI": info["doi"],
                "기본 최종 파일명": default_filename,
                "교수님 스타일 파일명": professor_filename,
                "APA 참고문헌": make_apa_plain(info),
                "APA 표시용": make_apa_markdown(info),
                "APA 서식 안내": make_apa_format_note(info),
                "상태": "성공"
            })

            pdf_files_for_zip.append({
                "filename": default_filename,
                "bytes": pdf_bytes
            })

        except Exception as e:
            results.append({
                "원래 파일명": original_name,
                "업로드 출처": source,
                "논문 구분": "",
                "상태": f"오류: {e}"
            })

        progress_bar.progress(idx / total_files)

    status_text.success("처리 완료!")

    df = pd.DataFrame(results)

    success_count = len(df[df["상태"] == "성공"])
    fail_count = total_files - success_count

    st.success(f"전체 {total_files}개 중 성공 {success_count}개, 실패 {fail_count}개")

    st.subheader("📋 정리 결과")
    st.dataframe(
        df.drop(columns=["APA 표시용"], errors="ignore"),
        use_container_width=True
    )

    csv = df.drop(columns=["APA 표시용"], errors="ignore").to_csv(index=False).encode("utf-8-sig")

    st.download_button(
        "📥 정리 결과 CSV 다운로드",
        data=csv,
        file_name="paper_renamer_results.csv",
        mime="text/csv"
    )

    if pdf_files_for_zip:
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            used_names = set()

            for file in pdf_files_for_zip:
                filename = file["filename"]

                if filename in used_names:
                    name_part = filename.replace(".pdf", "")
                    count = 2
                    new_filename = f"{name_part}_{count}.pdf"

                    while new_filename in used_names:
                        count += 1
                        new_filename = f"{name_part}_{count}.pdf"

                    filename = new_filename

                used_names.add(filename)
                zip_file.writestr(filename, file["bytes"])

        zip_buffer.seek(0)

        st.download_button(
            "📦 변경된 파일명으로 ZIP 다운로드",
            data=zip_buffer,
            file_name="renamed_papers.zip",
            mime="application/zip"
        )

    st.subheader("📌 복붙용 결과")

    for result in results:
        st.divider()
        st.markdown(f"### 원래 파일명: `{result['원래 파일명']}`")
        st.write(f"상태: **{result['상태']}**")

        if result["상태"] == "성공":
            st.write(f"업로드 출처: **{result['업로드 출처']}**")
            st.write(f"논문 구분: **{result['논문 구분']}**")

            st.markdown("#### 1. 기본 최종 파일명")
            st.code(result["기본 최종 파일명"])

            st.markdown("#### 2. 교수님 스타일 파일명")
            st.code(result["교수님 스타일 파일명"])

            st.markdown("#### 3. APA 참고문헌 복붙용")
            st.code(result["APA 참고문헌"])

            st.markdown("#### 4. APA 스타일 미리보기")
            st.markdown(result["APA 표시용"])

            st.markdown("#### 5. APA 서식 안내")
            st.info(result["APA 서식 안내"])

            st.markdown("#### 6. 논문 검색 바로가기")
            st.markdown(
                make_search_links({
                    "title": result["제목"],
                    "doi": result["DOI"]
                }),
                unsafe_allow_html=True
            )

        else:
            st.warning(
                "DOI 또는 제목 검색에 실패했습니다. "
                "스캔 PDF이거나, PDF 텍스트 추출이 어렵거나, "
                "Crossref에 메타데이터가 부족한 논문일 수 있습니다."
            )
