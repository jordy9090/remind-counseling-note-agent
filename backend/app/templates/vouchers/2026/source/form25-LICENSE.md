# Form 25 provenance and reuse

Reviewed on 2026-11-01. This template uses the Ministry of Health and Welfare's
**2026 Mental Health Psychological Counseling Voucher Program Guide**, Form 25,
printed pages 156–158 (PDF pages 162–164), published by Dobong Welfare on
2026-04-27. The publisher explicitly labels this guideline **KOGL Type 1
(attribution)**. This permits commercial use and adaptation with attribution.

- [Publisher and license notice](https://welfare.dobong.go.kr/dobongBokji/bbs/BMSR00004/view.do?boardId=1771&menuNo=200113)
- [Original guideline PDF](https://welfare.dobong.go.kr/user/cmmn/file/fileDown.do?atchFileId=a4ef18e57a874273be9d99e3d0fe97fd&fileSn=1)
- [Korea Copyright Commission: KOGL types](https://www.copyright.or.kr/gov/nuri/guide/index.do)
- Guideline SHA-256: `f76b0615e28225e4e58e68f4ddbf83a3bbb7fbc21e7c3b466abf234572ddc2d4`

The nine clauses were transcribed and compared character-for-character after
removing layout whitespace. No separate third-party restriction was found in
the relevant form. This is a source-license review, not a certification of an
individual institution's completed contract. The Gangnam page's Type 4 files
are not the source for this new template, and this review does not resolve
licensing of the older Form 10/26 assets.

Remind adds the required contract-term fields listed on printed page 98, leaves
identity/signature fields blank, and independently lays out editable text.
Circled paragraph numbers become `(1)`–`(4)` and half-width middle dots become
Korean middle dots because the bundled font lacks those source glyphs. The
clause wording is unchanged. Both outputs include publisher, work, page range,
KOGL type, modification notice, and source URL; the UI also links the source.
No official logo or endorsement is implied.

## Blank HWPX package

`form25-blank.hwpx` derives from `src/hwpx/data/Skeleton.hwpx` in
[airmang/python-hwpx](https://github.com/airmang/python-hwpx), commit
`3e5197c4c00c775b12dafe3a62942c3a8aa0941e`, under Apache-2.0.
Only the blank document package is used; the Python library is not installed
or executed. Metadata and preview assets are cleared/replaced. Generated files
replace fonts, paragraph styles, page layout and text. The upstream LICENSE
and NOTICE are preserved here and inside every generated HWPX archive, with
a modification notice. No font binaries are included in the HWPX.

The PDF embeds the existing Nanum Gothic font under `compiled/OFL.txt`.
See `../form25-manifest.json` for hashes of all rendering assets.
