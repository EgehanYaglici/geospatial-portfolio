# site/

The deployable portfolio. 37 MB, no build step, no framework, no server needed.

## Preview locally

    cd site
    python3 -m http.server 8000

Then open <http://localhost:8000>.

Opening `index.html` with a `file://` URL will not work properly: the maps and
the point cloud viewer fetch JSON and binary data, and browsers block that over
`file://`. Use the command above.

## Deploy

Upload the contents of this folder as a static site. Nothing needs to run
server side.

- Vercel or Netlify: drag the folder in, or point at this directory
- Cloudflare Pages: build command empty, output directory `site`
- GitHub Pages: publish from this directory
- S3 and CloudFront: sync the folder, index document `index.html`

Exclude `_to_delete/` from whatever you upload.

## Regenerate

    python3 tools/build_site.py

Copies each case study's web assets in from the project folders, compresses
oversized images, and lints for long dashes and broken local links. The page
HTML itself is authored by hand and is never overwritten by the build.

## External dependencies at runtime

- Google Fonts, IBM Plex Sans and Mono
- Mapbox GL JS, with a public token, for the four map pages

Both degrade gracefully. Three.js is vendored in `assets/vendor/`, so the point
cloud viewer has no CDN dependency.
