/**
 * ResizableImage — TipTap Image extension with an extra `width` attribute.
 *
 * The width is stored as a CSS value string (e.g. "50%", "300px") and is
 * rendered as an inline `style="width:…; height:auto;"` so it works both
 * in the TipTap editor and in the rendered HTML output shown in bot-ui.
 */
import Image from "@tiptap/extension-image";

export const ResizableImage = Image.extend({
  addAttributes() {
    return {
      // Keep all parent attributes (src, alt, title)
      ...this.parent?.(),

      width: {
        default: null,
        parseHTML: (element) =>
          element.style.width || element.getAttribute("width") || null,
        renderHTML: (attributes) => {
          if (!attributes.width) return {};
          return { style: `width: ${attributes.width}; height: auto;` };
        },
      },
    };
  },
});
