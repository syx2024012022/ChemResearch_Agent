import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

async function writeBlob(target, blob) {
  await fs.writeFile(target, new Uint8Array(await blob.arrayBuffer()));
}

function textbox(slide, name, text, position, style) {
  const shape = slide.shapes.add({
    geometry: "textbox", name, position, fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  const containsChinese = /[\u3400-\u9FFF]/u.test(text);
  shape.text.style = { typeface: containsChinese ? "SimHei" : "Arial", ...style };
  return shape;
}

async function addImage(slide, imagePath, position) {
  const bytes = await fs.readFile(imagePath);
  slide.images.add({
    blob: bytes, contentType: "image/png", alt: path.basename(imagePath),
    fit: "contain", position,
  });
}

async function main() {
  const [inputPath, outputDir] = process.argv.slice(2);
  const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
  if (payload.asset_override_dir) {
    for (const content of payload.contents) {
      for (const block of content.blocks || []) {
        if (block.asset_path) block.asset_path = path.join(payload.asset_override_dir, path.basename(block.asset_path));
      }
    }
  }
  await fs.mkdir(outputDir, { recursive: true });
  const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });
  for (const [index, content] of payload.contents.entries()) {
    const slide = deck.slides.add();
    slide.background.fill = index === 0 ? "#102A2E" : "#F7F4ED";
    const isTitle = index === 0;
    const templateBackground = isTitle
      ? payload.template_backgrounds?.title
      : payload.template_backgrounds?.content;
    if (templateBackground) {
      await addImage(slide, templateBackground, { left: 0, top: 0, width: 1280, height: 720 });
    }
    if (isTitle) {
      slide.background.fill = "#F7F4ED";
      if (templateBackground) {
        slide.shapes.add({
          geometry: "rect", name: "cover-body-cleanup",
          position: { left: 0, top: 144, width: 1280, height: 576 },
          fill: "#FFFFFF", line: { style: "solid", fill: "#FFFFFF", width: 0 },
        });
      } else {
        slide.shapes.add({
          geometry: "rect", name: "title-banner",
          position: { left: 0, top: 0, width: 1280, height: 150 },
          fill: "#1F55A5", line: { style: "solid", fill: "#1F55A5", width: 0 },
        });
      }
      textbox(slide, `title-${index + 1}`, content.title,
        templateBackground
          ? { left: 64, top: 154, width: 1152, height: 96 }
          : { left: 64, top: 34, width: 1152, height: 100 },
        { fontSize: templateBackground ? 26 : 38, bold: true, color: templateBackground ? "#102A2E" : "#FFFFFF", alignment: "center" });
      const authors = content.blocks.find((block) => block.slot === "authors")?.text || "";
      const publication = content.blocks.find((block) => block.slot === "publication")?.text || "";
      const toc = content.blocks.find((block) => block.slot === "toc_graphic");
      textbox(slide, "title-authors", authors, { left: 70, top: templateBackground ? 256 : 172, width: 1140, height: 36 },
        { fontSize: 22, color: "#102A2E" });
      textbox(slide, "title-publication", publication, { left: 70, top: templateBackground ? 294 : 216, width: 1140, height: 32 },
        { fontSize: 17, italic: true, color: "#38536A" });
      if (toc) await addImage(slide, toc.asset_path, { left: 80, top: templateBackground ? 334 : 280, width: 1120, height: templateBackground ? 325 : 370 });
    } else {
      if (!templateBackground) {
        slide.shapes.add({
          geometry: "rect", name: "content-title-banner",
          position: { left: 0, top: 0, width: 1280, height: 112 },
          fill: "#1F55A5", line: { style: "solid", fill: "#1F55A5", width: 0 },
        });
      }
      textbox(slide, `title-${index + 1}`, content.title,
        { left: 64, top: 24, width: 1152, height: 72 },
        { fontSize: 36, bold: true, color: "#FFFFFF", alignment: "center" });
      const message = content.blocks.find((block) => block.slot === "message")?.text || "";
      const showMessage = message && message !== content.title;
      const images = content.blocks.filter((block) => block.asset_path);
      const layout = content.layout;
      if (layout === "panel_triptych" && images.length >= 3) {
        await addImage(slide, images[0].asset_path, { left: 48, top: 116, width: 550, height: 260 });
        await addImage(slide, images[1].asset_path, { left: 48, top: 390, width: 550, height: 275 });
        await addImage(slide, images[2].asset_path, { left: 620, top: 112, width: 610, height: 558 });
      } else if (layout === "two_panels_fill" && images.length >= 2) {
        await addImage(slide, images[0].asset_path, { left: 38, top: 112, width: 590, height: 565 });
        await addImage(slide, images[1].asset_path, { left: 652, top: 112, width: 590, height: 565 });
      } else if (layout === "weighted_two_images" && images.length >= 2) {
        await addImage(slide, images[0].asset_path, { left: 38, top: 112, width: 525, height: 565 });
        await addImage(slide, images[1].asset_path, { left: 582, top: 112, width: 660, height: 565 });
      } else if (layout === "stacked_mechanism_overview" && images.length >= 2) {
        await addImage(slide, images[0].asset_path, { left: 12, top: 82, width: 1256, height: 202 });
        await addImage(slide, images[1].asset_path, { left: 250, top: 282, width: 780, height: 430 });
      } else if (images.length >= 2 || layout === "two_images") {
        if (images[0]) await addImage(slide, images[0].asset_path, { left: 64, top: 132, width: 550, height: 510 });
        if (images[1]) await addImage(slide, images[1].asset_path, { left: 666, top: 132, width: 550, height: 510 });
        if (showMessage) textbox(slide, `message-${index + 1}`, message,
          { left: 64, top: 600, width: 1152, height: 64 },
          { fontSize: 18, color: "#25383B" });
      } else if (images.length === 1) {
        const imageLeft = layout === "image_left";
        const imageFull = layout === "image_full";
        const multiPanelFull = layout === "multipanel_full";
        const imagePos = multiPanelFull ? { left: 16, top: 102, width: 1248, height: 610 }
          : imageFull ? { left: 80, top: 126, width: 1120, height: 530 }
          : imageLeft ? { left: 64, top: 132, width: 720, height: 520 }
          : { left: 445, top: 132, width: 775, height: 520 };
        await addImage(slide, images[0].asset_path, imagePos);
        const textPos = imageFull || multiPanelFull ? { left: 80, top: 606, width: 1120, height: 62 }
          : imageLeft ? { left: 790, top: 190, width: 410, height: 300 }
          : { left: 102, top: 244, width: 292, height: 226 };
        if (showMessage && !imageFull && !multiPanelFull && !imageLeft) {
          slide.shapes.add({
            geometry: "ellipse", name: `message-circle-${index + 1}`,
            position: { left: 68, top: 180, width: 360, height: 360 },
            fill: "none", line: { style: "solid", fill: "#B7B7B7", width: 1.5 },
          });
        }
        if (showMessage) textbox(slide, `message-${index + 1}`, message, textPos,
          {
            fontSize: imageFull || multiPanelFull || imageLeft ? 20 : 26,
            bold: !imageFull && !multiPanelFull && !imageLeft,
            color: imageFull || multiPanelFull || imageLeft ? "#25383B" : "#000000",
            alignment: imageFull || multiPanelFull || imageLeft ? "left" : "center",
          });
      } else {
        textbox(slide, `message-${index + 1}`, message,
          { left: 120, top: 220, width: 1040, height: 240 },
          { fontSize: 38, bold: true, color: "#1F55A5", alignment: "center" });
      }
      if (templateBackground) {
        slide.shapes.add({
          geometry: "rect", name: `page-cleanup-${index + 1}`,
          position: { left: 1150, top: 668, width: 86, height: 38 },
          fill: "#FFFFFF", line: { style: "solid", fill: "#FFFFFF", width: 0 },
        });
      }
      textbox(slide, `page-${index + 1}`, String(index + 1), { left: 1160, top: 675, width: 56, height: 24 },
        { fontSize: 12, color: "#6B7B7D", alignment: "right" });
    }
    slide.speakerNotes.textFrame.setText(content.speaker_notes || "[Sources]\n- none");
    slide.speakerNotes.setVisible(true);
  }
  for (const [index, slide] of deck.slides.items.entries()) {
    await writeBlob(path.join(outputDir, `slide-${String(index + 1).padStart(2, "0")}.png`),
      await deck.export({ slide, format: "png", scale: 1 }));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(outputDir, `slide-${String(index + 1).padStart(2, "0")}.layout.json`), await layout.text());
  }
  await writeBlob(path.join(outputDir, "montage.webp"), await deck.export({ format: "webp", montage: true, scale: 1 }));
  const pptx = await PresentationFile.exportPptx(deck);
  await pptx.save(path.join(outputDir, "presentation.pptx"));
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
