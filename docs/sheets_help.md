# Frequently Asked Questions (FAQ)

### General Questions

**Q: How do I ensure everything functions smoothly?**
A: Great question! To keep our spreadsheets functioning smoothly, follow these simple habits:
   - Do not insert rows. This breaks the formulas. You can achive the same by copying the botom rows then delete and paste special (values only) lower.
   - Especially do not insert above the first data row. This will break formulas.
   - Only sort columns that are designated for sorting.
   - Similarly, only apply filters to designated filtering fields.
   - Always use the "Paste Special -> Paste Values Only" option when pasting data.
   
   - Some parts of the sheet are protected to prevent accidental edits. If you see a warning, please heed it and do not override.

**Q: Are there plans to develop a dedicated graphical user interface (GUI)?**
A: Absolutely! We're working towards a real GUI that will make your experience even smoother. Stay tuned!

**Q: What is 'Multiple Select' in the Sheets Crew Menu?**
A: Since Google Sheets doesn't natively support multiple selections in dropdown menus, our 'Multiple Select' tool fills this gap. To use it, simply click on the cell where you want to make multiple selections, then navigate to Sheets Crew -> Multiple Select.

**Q: What should I do with confusing columns, like 'num_ctx'?**
A: If you encounter confusing columns, a good rule of thumb is to copy values from the row above to maintain consistency. Still puzzled? We're here to help! Feel free to ask your question on our project page: [CrewAI Sheets UI GitHub](https://github.com/yuriwa/crewai-sheets-ui).

**Q: How can I set the same Language Learning Model (LLM) across all configurations quickly?**
A: To streamline your setup, go to the Models sheet and set your preferred model as 'TRUE' in the Default field. This setting ensures that unless specified otherwise in advanced settings, all tools and functions will use the default model.

### Advanced Questions

**Q: How can I add a new model from Ollama or Huggingface**
A: Adding a new model is straightforward:
   - Insert a new row in the Models sheet.
   - Copy and paste the 'model:version' exactly as it appears on the Ollama / Huggingface site into the designated field.
   - Fill out the remaining fields, and you're all set to use your new model!



