/**
 * SMART TILER API - CORE ENGINE
 * 
 * This file contains the standalone logic required to generate high-fidelity,
 * Mapbox-compatible map tiles from a raw image and 4 geographic coordinate points.
 * 
 * This engine is designed to be headless and UI-agnostic.
 * 
 * ==========================================
 * INTEGRATION WORKFLOW
 * ==========================================
 * 
 * To generate a tile, follow these steps:
 * 
 * 1. Initialize the Source Image:
 *    Load your raw image into an HTMLImageElement or Canvas.
 * 
 * 2. Define Georeferencing Corners (LngLat):
 *    Provide the exact GPS coordinates (Longitude/Latitude) for the Top-Left, 
 *    Top-Right, Bottom-Right, and Bottom-Left corners of the raw image.
 * 
 * 3. Calculate Homography Matrix:
 *    Call `TileEngine.calculateHomography(img.width, img.height, corners)`.
 *    This returns a 3x3 transformation matrix solving perspective distortion.
 * 
 * 4. Build Mipmap Quality Pyramid (Anti-Aliasing):
 *    Call `TileEngine.buildMipmaps(img)`. This generates downscaled versions
 *    of your image to prevent moiré patterns at low zoom levels.
 * 
 * 5. Render Tile:
 *    Call `TileEngine.generateTile(z, x, y, homographyMatrix, mipmaps)`.
 *    This will return an HTMLCanvasElement containing the 512x512 tile pixel data,
 *    or `null` if the tile is empty (ocean/outside bounds).
 */

const TileEngine = {

    // --- 1. GEOSPATIAL HELPER FUNCTIONS ---
    // Converts [0,1] Mercator space to/from real-world GPS coordinates

    _mxToLon: (x) => x * 360 - 180,
    _myToLat: (y) => {
        const n = Math.PI * (1 - 2 * y);
        return 180 / Math.PI * Math.atan(.5 * (Math.exp(n) - Math.exp(-n)));
    },
    _lonToMx: (l) => (l + 180) / 360,
    _latToMy: (a) => {
        const r = a * Math.PI / 180;
        return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2;
    },

    // --- 2. PERPSECTIVE SOLVER (HOMOGRAPHY) ---

    /**
     * Calculates the 3x3 Projective Transformation (Homography) matrix.
     * Uses Gaussian Elimination to map the 4 bent geographic corners onto the flat image corners.
     * 
     * @param {number} imgW - Width of the source image in pixels
     * @param {number} imgH - Height of the source image in pixels
     * @param {Object} corners - Object with {tl, tr, br, bl} containing {lng, lat}
     * @returns {Array} - The 9-element Homography Matrix array.
     */
    calculateHomography: function (imgW, imgH, corners) {
        const pts = [
            { mx: this._lonToMx(corners.tl.lng), my: this._latToMy(corners.tl.lat), px: 0, py: 0 },
            { mx: this._lonToMx(corners.tr.lng), my: this._latToMy(corners.tr.lat), px: imgW, py: 0 },
            { mx: this._lonToMx(corners.br.lng), my: this._latToMy(corners.br.lat), px: imgW, py: imgH },
            { mx: this._lonToMx(corners.bl.lng), my: this._latToMy(corners.bl.lat), px: 0, py: imgH }
        ];

        const A = [], B = [];
        for (let i = 0; i < 4; i++) {
            A.push([pts[i].mx, pts[i].my, 1, 0, 0, 0, -pts[i].mx * pts[i].px, -pts[i].my * pts[i].px]);
            B.push(pts[i].px);
            A.push([0, 0, 0, pts[i].mx, pts[i].my, 1, -pts[i].mx * pts[i].py, -pts[i].my * pts[i].py]);
            B.push(pts[i].py);
        }

        // Gaussian elimination for 8x8 system
        const n = 8;
        for (let i = 0; i < n; i++) {
            let max = i;
            for (let j = i + 1; j < n; j++) if (Math.abs(A[j][i]) > Math.abs(A[max][i])) max = j;
            [A[i], A[max]] = [A[max], A[i]];
            [B[i], B[max]] = [B[max], B[i]];

            for (let j = i + 1; j < n; j++) {
                const factor = A[j][i] / A[i][i];
                B[j] -= factor * B[i];
                for (let k = i; k < n; k++) A[j][k] -= factor * A[i][k];
            }
        }
        const x = new Array(n);
        for (let i = n - 1; i >= 0; i--) {
            let sum = 0;
            for (let j = i + 1; j < n; j++) sum += A[i][j] * x[j];
            x[i] = (B[i] - sum) / A[i][i];
        }
        return [...x, 1];
    },

    // --- 3. QUALITY PYRAMID (MIPMAPS) ---

    /**
     * Pre-computes anti-aliased, downscaled versions of the source image.
     * Replaces the need for external tools like GDAL.
     * 
     * @param {HTMLImageElement|HTMLCanvasElement} sourceImage - The raw image.
     * @returns {Promise<Array>} - Pyramid array containing {source(Canvas), width, height, scale}.
     */
    buildMipmaps: async function (sourceImage) {
        const imgW = sourceImage.width || sourceImage.naturalWidth;
        const imgH = sourceImage.height || sourceImage.naturalHeight;

        const mipmaps = [{ source: sourceImage, width: imgW, height: imgH, scale: 1 }];

        let prevW = imgW, prevH = imgH, prevSource = sourceImage;

        // Use Pica if available globally (Lanczos3), else fallback to basic Canvas drawing
        const usePica = typeof pica !== 'undefined';
        const picaInst = usePica ? pica() : null;

        while (prevW > 512 || prevH > 512) {
            const nw = Math.max(1, Math.floor(prevW / 2));
            const nh = Math.max(1, Math.floor(prevH / 2));

            const nextCanvas = document.createElement('canvas');
            nextCanvas.width = nw; nextCanvas.height = nh;

            if (usePica) {
                await picaInst.resize(prevSource, nextCanvas, { quality: 3 });
            } else {
                nextCanvas.getContext('2d').drawImage(prevSource, 0, 0, nw, nh);
            }

            mipmaps.push({ source: nextCanvas, width: nw, height: nh, scale: mipmaps[mipmaps.length - 1].scale * 2 });
            prevSource = nextCanvas;
            prevW = nw; prevH = nh;
        }
        return mipmaps;
    },

    // --- 4. TILE RENDERING KERNEL ---

    /**
     * Generates a single 512px tile by performing Reverse Perspective Mapping.
     * Uses Bilinear Interpolation for smooth sub-pixel mapping.
     * 
     * @param {number} z - Target Zoom Level
     * @param {number} x - Target Tile X coordinate
     * @param {number} y - Target Tile Y coordinate
     * @param {Array} homography - The 9-element Homography Matrix
     * @param {Array} mipmaps - The Mipmap pyramid array
     * @param {Object} corners - Optional: Coordinates for bounding box culling (optimization)
     * @returns {HTMLCanvasElement|null} - A 512x512 canvas, or null if the tile is empty.
     */
    generateTile: function (z, x, y, homography, mipmaps, corners = null) {
        const tileSize = 512;
        const n = Math.pow(2, z);
        const tL = x / n, tR = (x + 1) / n, tT = y / n, tB = (y + 1) / n;

        // Optimization: Culling (skip oceans/empty space immediately)
        if (corners) {
            const mxs = [this._lonToMx(corners.tl.lng), this._lonToMx(corners.tr.lng), this._lonToMx(corners.br.lng), this._lonToMx(corners.bl.lng)];
            const mys = [this._latToMy(corners.tl.lat), this._latToMy(corners.tr.lat), this._latToMy(corners.br.lat), this._latToMy(corners.bl.lat)];
            const bb = { minX: Math.min(...mxs), maxX: Math.max(...mxs), minY: Math.min(...mys), maxY: Math.max(...mys) };
            if (tR <= bb.minX || tL >= bb.maxX || tB <= bb.minY || tT >= bb.maxY) return null; // Totally Outside
        }

        // Helper: Convert Mercator to Image Pixel via Homography
        const _mercToPx = (mx, my, h) => {
            const d = h[6] * mx + h[7] * my + h[8];
            return { x: (h[0] * mx + h[1] * my + h[2]) / d, y: (h[3] * mx + h[4] * my + h[5]) / d };
        };

        const h = homography;
        const pTL = _mercToPx(tL, tT, h), pTR = _mercToPx(tR, tT, h);
        const pBL = _mercToPx(tL, tB, h), pBR = _mercToPx(tR, tB, h);

        const srcMinX = Math.min(pTL.x, pTR.x, pBL.x, pBR.x);
        const srcMinY = Math.min(pTL.y, pTR.y, pBL.y, pBR.y);
        const srcMaxX = Math.max(pTL.x, pTR.x, pBL.x, pBR.x);
        const srcMaxY = Math.max(pTL.y, pTR.y, pBL.y, pBR.y);
        const srcSpanW = srcMaxX - srcMinX, srcSpanH = srcMaxY - srcMinY;

        if (srcSpanW <= 0 || srcSpanH <= 0 || !isFinite(srcMinX)) return null;

        // Auto-select optimal Mipmap tier to prevent aliasing
        const scaleFactor = Math.max(srcSpanW, srcSpanH) / tileSize;
        let mipLevel = 0;
        for (let i = 1; i < mipmaps.length; i++) {
            if (mipmaps[i].scale <= scaleFactor * 0.75) mipLevel = i; else break;
        }
        const mip = mipmaps[mipLevel];
        const ms = mip.scale;

        // Extract Region of Interest (ROI) from Mipmap
        const pad = 2;
        const rMinX = Math.max(0, Math.floor(srcMinX / ms) - pad);
        const rMinY = Math.max(0, Math.floor(srcMinY / ms) - pad);
        const rMaxX = Math.min(mip.width, Math.ceil(srcMaxX / ms) + pad);
        const rMaxY = Math.min(mip.height, Math.ceil(srcMaxY / ms) + pad);
        const rW = rMaxX - rMinX, rH = rMaxY - rMinY;

        if (rW <= 0 || rH <= 0) return null;

        const tmpCanvas = document.createElement('canvas');
        tmpCanvas.width = rW; tmpCanvas.height = rH;
        tmpCanvas.getContext('2d').drawImage(mip.source, rMinX, rMinY, rW, rH, 0, 0, rW, rH);
        const regionData = tmpCanvas.getContext('2d').getImageData(0, 0, rW, rH).data;

        // Setup Output Canvas
        const outCanvas = document.createElement('canvas');
        outCanvas.width = tileSize; outCanvas.height = tileSize;
        const outCtx = outCanvas.getContext('2d');
        const outImgData = outCtx.createImageData(tileSize, tileSize);
        const od = outImgData.data;

        let opaqueCount = 0;
        const dxMerc = (tR - tL) / tileSize, dyMerc = (tB - tT) / tileSize;
        const rW4 = rW * 4;

        // --- SUB-PIXEL RENDERING LOOP (Bilinear Interpolation) ---
        for (let oy = 0; oy < tileSize; oy++) {
            const my = tT + (oy + 0.5) * dyMerc; // Target Mercator Y (center of pixel)

            for (let ox = 0; ox < tileSize; ox++) {
                const mx = tL + (ox + 0.5) * dxMerc; // Target Mercator X (center of pixel)

                // 1. Reverse Map: Target Pixel -> Source Pixel
                const denom = h[6] * mx + h[7] * my + h[8];
                const spx = (h[0] * mx + h[1] * my + h[2]) / denom;
                const spy = (h[3] * mx + h[4] * my + h[5]) / denom;

                // 2. Adjust Source Pixel to ROI coordinates
                const sx = spx / ms - rMinX;
                const sy = spy / ms - rMinY;

                const idx = (oy * tileSize + ox) * 4;

                // Bounds Check
                if (sx < 0 || sy < 0 || sx >= rW - 1 || sy >= rH - 1) {
                    od[idx] = od[idx + 1] = od[idx + 2] = od[idx + 3] = 0; // Transparent
                    continue;
                }

                // 3. Bilinear Interpolation (Smooth Sampling)
                const x0 = sx | 0, y0 = sy | 0;
                const fx = sx - x0, fy = sy - y0;

                const i00 = (y0 * rW + x0) * 4;
                const i10 = i00 + 4;
                const i01 = i00 + rW4;
                const i11 = i01 + 4;

                const w00 = (1 - fx) * (1 - fy), w10 = fx * (1 - fy);
                const w01 = (1 - fx) * fy, w11 = fx * fy;

                od[idx] = (regionData[i00] * w00 + regionData[i10] * w10 + regionData[i01] * w01 + regionData[i11] * w11 + 0.5) | 0; // R
                od[idx + 1] = (regionData[i00 + 1] * w00 + regionData[i10 + 1] * w10 + regionData[i01 + 1] * w01 + regionData[i11 + 1] * w11 + 0.5) | 0; // G
                od[idx + 2] = (regionData[i00 + 2] * w00 + regionData[i10 + 2] * w10 + regionData[i01 + 2] * w01 + regionData[i11 + 2] * w11 + 0.5) | 0; // B
                od[idx + 3] = (regionData[i00 + 3] * w00 + regionData[i10 + 3] * w10 + regionData[i01 + 3] * w01 + regionData[i11 + 3] * w11 + 0.5) | 0; // A

                if (od[idx + 3] > 10) opaqueCount++; // Count non-transparent pixels
            }
        }

        if (opaqueCount === 0) return null; // Reject entirely empty tiles

        outCtx.putImageData(outImgData, 0, 0);
        return outCanvas;
    },

    // --- 5. BATCH EXPORT KERNEL (THE LOOP & ZIP BUILDER) ---

    /**
     * Demonstrates the complete logic required to loop through zoom levels,
     * generate all necessary tiles, and package them into a Standard Z/X/Y Folder Zip.
     * 
     * @param {Object} JSZipObject - A new instance of JSZip (new JSZip()).
     * @param {number} zMin - Minimum zoom level.
     * @param {number} zMax - Maximum zoom level.
     * @param {Array} homographyMatrix - Calculated in Step 1.
     * @param {Array} mipmaps - Calculated in Step 2.
     * @param {Object} corners - The original gps boundary corners {tl, tr, br, bl}.
     * @param {Function} onProgress - Optional callback for UI progress updates.
     * @returns {Promise<Blob>} - A promise that resolves to the final ZIP Blob.
     */
    exportTilesToZip: async function (JSZipObject, zMin, zMax, homographyMatrix, mipmaps, corners, onProgress) {

        // 1. Calculate Minimum Bounding Box (Mercator)
        const mxs = [this._lonToMx(corners.tl.lng), this._lonToMx(corners.tr.lng), this._lonToMx(corners.br.lng), this._lonToMx(corners.bl.lng)];
        const mys = [this._latToMy(corners.tl.lat), this._latToMy(corners.tr.lat), this._latToMy(corners.br.lat), this._latToMy(corners.bl.lat)];
        const bb = { minX: Math.min(...mxs), maxX: Math.max(...mxs), minY: Math.min(...mys), maxY: Math.max(...mys) };

        // 2. Queue all required physical coordinates into a processing list
        const queue = [];
        for (let z = zMin; z <= zMax; z++) {
            const n = Math.pow(2, z);
            for (let x = Math.floor(bb.minX * n); x <= Math.floor(bb.maxX * n); x++) {
                for (let y = Math.floor(bb.minY * n); y <= Math.floor(bb.maxY * n); y++) {
                    queue.push({ z, x, y });
                }
            }
        }

        let saved = 0, skipped = 0;
        const BATCH_SIZE = 16; // Prevent freezing the JS Event Loop

        // 3. Process the queue in parallel batches
        for (let i = 0; i < queue.length; i += BATCH_SIZE) {
            const batch = queue.slice(i, i + BATCH_SIZE);

            // Render 16 tiles simultaneously using Promise.all
            const promises = batch.map(t => new Promise(resolve => {
                const canvas = this.generateTile(t.z, t.x, t.y, homographyMatrix, mipmaps, corners);
                if (canvas) {
                    canvas.toBlob(blob => resolve({ tile: t, blob }), 'image/png');
                } else {
                    resolve({ tile: t, blob: null }); // Skipped empty space
                }
            }));

            const results = await Promise.all(promises);

            // 4. Inject successful Blobs into the ZIP tree structure
            for (let res of results) {
                if (res.blob) {
                    JSZipObject.file(`tiles/${res.tile.z}/${res.tile.x}/${res.tile.y}.png`, res.blob);
                    saved++;
                } else {
                    skipped++;
                }
            }

            // Optional: Call the developer's UI progress bar
            if (onProgress) onProgress(((i + batch.length) / queue.length) * 100, saved, skipped);

            // Yield to main thread
            await new Promise(r => setTimeout(r, 0));
        }

        // 5. Build and return the final physical archive file
        return await JSZipObject.generateAsync({ type: 'blob' });
    }
};

// Export for module systems if used, attach to window otherwise.
if (typeof module !== 'undefined' && module.exports) module.exports = TileEngine;
else window.TileEngine = TileEngine;
