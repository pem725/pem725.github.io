// Academic CV Template - Clean, Conservative, Professional
// Inspired by Harvard Career Services guidelines

#let academic-cv(
  title: none,
  author: none,
  affiliation: none,
  email: none,
  phone: none,
  address: none,
  date: datetime.today().display("[month repr:long] [day], [year]"),
  body,
) = {
  // Document settings
  set document(title: title, author: author)

  // Page setup - generous margins for readability
  set page(
    paper: "us-letter",
    margin: (top: 0.75in, bottom: 0.75in, left: 1in, right: 1in),
    footer: context [
      #set text(size: 9pt, fill: rgb("#666666"))
      #author #h(1fr) Page #counter(page).display() of #counter(page).final().first()
    ]
  )

  // Typography - professional academic style
  set text(
    font: "Linux Libertine",
    size: 11pt,
    lang: "en",
  )

  // Headings
  set heading(numbering: none)
  show heading.where(level: 1): it => {
    v(0.5em)
    text(size: 14pt, weight: "bold", fill: rgb("#2c3e50"))[#it.body]
    v(-0.3em)
    line(length: 100%, stroke: 0.5pt + rgb("#2c3e50"))
    v(0.3em)
  }

  show heading.where(level: 2): it => {
    v(0.4em)
    text(size: 12pt, weight: "bold")[#it.body]
    v(0.2em)
  }

  show heading.where(level: 3): it => {
    v(0.3em)
    text(size: 11pt, weight: "bold", style: "italic")[#it.body]
    v(0.1em)
  }

  // Links
  show link: it => text(fill: rgb("#2c3e50"))[#it]

  // Lists - tighter spacing
  set list(indent: 1em, spacing: 0.65em)
  set enum(indent: 1em, spacing: 0.65em)

  // Paragraphs
  set par(justify: true, leading: 0.65em)

  // Header
  align(center)[
    #text(size: 18pt, weight: "bold")[#author]
    #v(-0.3em)
    #text(size: 11pt, fill: rgb("#555555"))[#affiliation]
    #v(0.2em)
    #text(size: 10pt)[
      #if email != none [#link("mailto:" + email)[#email]]
      #if phone != none [ | #phone]
    ]
    #if address != none [
      #v(-0.2em)
      #text(size: 10pt)[#address]
    ]
  ]

  v(0.5em)
  line(length: 100%, stroke: 1pt + rgb("#2c3e50"))
  v(0.5em)

  // Body
  body

  // Footer note
  v(1em)
  line(length: 100%, stroke: 0.5pt + rgb("#cccccc"))
  v(0.3em)
  align(center)[
    #text(size: 9pt, fill: rgb("#888888"))[
      Last updated: #date
    ]
  ]
}

#let entry(
  title: none,
  subtitle: none,
  date: none,
  description: none,
) = {
  grid(
    columns: (1fr, auto),
    gutter: 1em,
    [
      #if title != none [#strong[#title]]
      #if subtitle != none [, #subtitle]
      #if description != none [
        #v(-0.2em)
        #text(size: 10pt)[#description]
      ]
    ],
    align(right)[#text(size: 10pt)[#date]]
  )
  v(0.3em)
}
