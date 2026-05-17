import streamlit as st
import fitz
import re
import requests
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="PaperRenamer", layout="wide")

st.title("📚 PaperRenamer")
st.write("논문 PDF를 업로드한 뒤 [변경하기] 버튼을 누르면 자동 정리됩니다.")

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
    "PDF 파일 업로드",
    type=["pdf"],
    accept_multiple_files=True
)

start_button = st.button("🚀 변경하기")


def clean_filename(text):
    invalid_chars = '\\/:*?"<>|'
    for ch in invalid_chars:
        text = text.replace(ch, "")
    return re.sub(r"\s+", " ", text).strip()


def is_korean_paper(info):
    target_text = (
        info.get("title", "") +
        info.get("journal", "") +
        " ".join([a.get("family", "") for a in info.get("authors", [])])
    )
    return bool(re.search(r"[가-힣]", target_text))


def find_doi(text):
    doi_pattern = r"10\.\d{4,9}/[-._;()/:A-Z0-9]+"
    match = re.search(doi_pattern, text, re.I)
    if match:
        return match.group(0).rstrip(".,;)")
    return None


def extract_possible_title(text):
    lines = text.split("\n")
    candidates = []

    for line in lines:
        line = line.strip()

        if len(line) < 15:
            continue
        if "doi" in line.lower():
            continue
        if re.search(r"10\.\d", line):
            continue
        if len(line.split()) > 30:
            continue

        candidates.append(line)

    return candidates[0] if candidates else None


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
    params = {"query.title": title, "rows": 1}

    response = requests.get(url, params=params, timeout=10)

    if response.status_code != 200:
        return None

    items = response.json()["message"]["items"]

    if not items:
        return None

    doi = items[0].get("DOI", "")

    if not doi:
        return None

    return get_crossref_info(doi)


def read_pdf_text(uploaded_file):
    pdf_bytes = uploaded_file.read()
    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")

    text = ""
    for page_num in range(min(3, len(pdf))):
        text += pdf[page_num].get_text()

    return text, pdf_bytes


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


if uploaded_files and not start_button:
    st.warning("PDF 업로드가 완료되었습니다. 정리를 시작하려면 [🚀 변경하기] 버튼을 눌러주세요.")


if uploaded_files and start_button:
    results = []
    pdf_files_for_zip = []

    progress_bar = st.progress(0)
    status_text = st.empty()

    total_files = len(uploaded_files)

    for idx, uploaded_file in enumerate(uploaded_files, start=1):
        status_text.write(f"처리 중: {idx} / {total_files} - {uploaded_file.name}")

        try:
            text, pdf_bytes = read_pdf_text(uploaded_file)

            doi = find_doi(text)
            info = get_crossref_info(doi) if doi else None

            if not info:
                possible_title = extract_possible_title(text)
                if possible_title:
                    info = get_crossref_info_by_title(possible_title)

            if not info:
                results.append({
                    "원래 파일명": uploaded_file.name,
                    "논문 구분": "",
                    "상태": "자동 정리 실패"
                })
                progress_bar.progress(idx / total_files)
                continue

            paper_type = "국문" if is_korean_paper(info) else "해외"

            default_filename = make_default_filename(info)
            professor_filename = make_professor_filename(info)

            results.append({
                "원래 파일명": uploaded_file.name,
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
                "원래 파일명": uploaded_file.name,
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

        else:
            st.warning(
                "DOI 또는 제목 검색에 실패했습니다. "
                "스캔 PDF이거나, PDF 텍스트 추출이 어렵거나, "
                "Crossref에 메타데이터가 부족한 논문일 수 있습니다."
            )