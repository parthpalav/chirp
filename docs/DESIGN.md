# Chirp interface

Chirp is a Flask and SQLite application rendered through Jinja. Its interface
uses standard HTML forms and links; no frontend framework or build step is
required.

## Design direction

The visual system draws from Swiss typography and IBM Carbon's product UI:

- A dark header and neutral navigation frame the primary content.
- A consistent grid separates the timeline from supporting information.
- IBM Plex Sans Light provides heading hierarchy; Regular handles body text;
  Semibold is reserved for emphasis. IBM Plex Mono identifies metadata.
- White and gray surfaces, thin rules, and square corners replace floating cards.
- Carbon Blue 60 (`#0f62fe`) identifies primary actions and the active navigation
  item. Running text stays neutral.
- Short labels describe actual functions. There are no emoji, decorative
  gradients, engagement counters, or controls for unsupported features.

## Implementation

`static/style.css` contains the color variables, font declarations, shell,
components, and responsive layouts. IBM Plex fonts and their SIL Open Font
License are stored in `static/fonts/`, allowing offline use.

`templates/base.html` supplies the shared header, navigation, and skip link.
`templates/components.html` supplies the line icons and the post component
used by both the timeline and profiles.

The feed's member list and each profile's posts are queried from SQLite.
The application routes, form field names, authentication behavior, and
intentional vulnerability paths are preserved.

At narrower desktop widths, the supporting rail moves below the main content.
At 640px and below, navigation becomes a horizontal row and content uses a
single column. Wide tables and navigation can scroll within their own regions.
Inputs have explicit labels, errors are announced with `role="alert"`, and
interactive elements have visible keyboard focus states.

## References

- [Carbon typography](https://www.carbondesignsystem.com/building-blocks/foundations/typography/overview)
- [Carbon spacing](https://www.carbondesignsystem.com/building-blocks/foundations/spacing/overview)
- [Carbon UI shell](https://www.carbondesignsystem.com/building-blocks/core/components/ui-shell-header/specifications)
- [IBM Plex source and license](https://github.com/IBM/plex)

This is a Carbon-inspired interface, implemented with local CSS and Jinja,
rather than a dependency on the Carbon component library.
