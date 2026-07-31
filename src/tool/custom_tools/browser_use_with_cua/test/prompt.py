# PROMPT = """
#     Open http://epic-ai-tokarev.ddns.hysdev.com:8889/#!/myTasks
# Login:
# - Username: Cas P
# - Password: Epica23!

# Navigate to the “Resource management” section.
# Then click on plus icon near Groups: create a multigroup named “multigroup2”.
# Then use same flow to create a group named “group2”.
# Open “multigroup2” → Subgroups → tick “group2”.
# Summarize steps done.

# """

PROMPT = """You are an assistant that performs browser actions following exact step-by-step instructions.

1. Open the following URL:  
   http://epic-ai-tokarev.ddns.hysdev.com:8889/#!/myTasks 

2. Log in using these credentials:  
   - Username: `Cas P`  
   - Password: `Epica23!`

3. Find the Resource management tab and navigate to it.

4. Find and click the plus icon to the right of the word "Groups" in the first row of the left column.  
    4.1. After clicking, a window titled "Create New" should appear.  
    4.2. In that window, select the option "Multigroup".  
    4.3. After selecting "Multigroup", immediately type "multigroup2" and press Enter.  
    4.4. Confirm that the name "multigroup2" is displayed correctly and the input field is no longer editable.


5. Again, find and click the plus icon to the right of the word "Groups" in the first row of the left column.
   5.1. After clicking, a window titled "Create New" should appear.
   5.2. In that window, select the option "Group".
   5.3. After selecting "Group", immediately type "group2" and press Enter.
   5.4. Confirm that the name "group2" is displayed correctly and the input field is no longer editable.

     
6. Click on the multigroup named multigroup1 to open its details.
    In the details window, find the "Subgroups" section and click the green plus icon to the right.
    In the popup, select the group named group2 by checking the box next to it.
    Click anywhere outside the popup to close it.
"""


TASK_PROMPT = """
You are testing a web application called **EpicFlow**.

Follow the test case below step by step, simulating a real user's behavior: clicking, scrolling, typing, navigating with the keyboard, etc.
Do not explain your thought process or describe your reasoning.  
Just perform the actions and briefly describe what happened on screen after each step.  
At the end of your response, clearly state either `PASSED` or `FAILED` on a separate line.  
If something fails, describe briefly what happened or what was on screen.  
Do not include any `Reasoning:` or detailed internal logic.  
Do not ask for confirmation or permission.

**Steps:**

1. Open the following URL:  
   http://epic-ai-tokarev.ddns.hysdev.com:8889/#!/login  
   - Use the browser’s address bar to enter the full URL and press Enter.  


2. Log in using these credentials:  
   - Username: `Cas P`  
   - Password: `Epica23!`
   Follow this procedure for logging in:  
   1) Click into the **Username** input field, type the username `Cas P`, then press **Tab**.  
   2) Click into the **Password** input field, type the password `Epica23!`, then press **Tab** to dismiss any warning messages.  
   3) Finally, click the login button to submit.

3. In the left sidebar menu (the vertical menu on the left side of the screen), locate the icon showing two people (a silhouette of two human figures).
    This icon is positioned approximately in the middle of the sidebar.
    Hover your mouse over the icon. A tooltip labeled "Resource management" should appear.
    In some cases, the label "Resource management" may be shown directly below the icon instead of as a tooltip.
    Once you confirm the label says "Resource management", click directly on the icon (not the label).
    After clicking, ensure that a table with users and groups is visible on the screen.
    If the table is not visible, it means the wrong tab was opened — go back to the sidebar and try clicking the correct icon again.

4. In the **first (left) column**, on the **first row**, locate the word **"Groups"**.  
   - To the right of the word "Groups," click the **blue plus icon**.  
   - A window titled **"Create New"** will appear.  
   - In this window, click on **"Multigroup"**.  
   - Enter the name `test` for the multigroup.  
   - Press **Enter** to confirm and create the multigroup.

5. In the **first (left) column**, on the **first row**, locate the word **"Groups"**.  
   - To the right of the word "Groups," click the **blue plus icon**.  
   - A window titled **"Create New"** will appear.  
   - In this window, click on **"Group"**.  
   - Enter the name `example` for the group.  
   - Press **Enter** to confirm and create the group.

6. Click on the multigroup name `test` to open its details window or panel.  
   - In the opened group details window, scroll down until you see the "Subgroups" section.  
   - To the right of the word "Subgroups", click the **green plus icon**.  
   - A popup window will appear with a list of available groups.  
   - Find the group named `example` and check the box next to it to add it as a subgroup.  
   - To finish adding, click the left mouse button anywhere outside the popup window to close it.  
   - Note: After this step, the position of the multigroup `test` in the table may change.  
     Be attentive and locate it again by its name if its position has changed.

7. Click on the multigroup name test again to reopen its details window.
    Important: After the previous step (adding a subgroup), the position of the multigroup test in the table may have changed.
    Do not click on any other group — make sure you are clicking on the correct multigroup whose name is exactly test.
    This will open a popup details window directly below the test multigroup row in the table.
    Inside this specific popup window, scroll down until you see the Subgroups section.
    Locate the subgroup named example.
    To the right of example, you will see a gray upward arrow icon.
    This icon is positioned above the Delete icon.
    Hover over the gray upward arrow icon.
    If the tooltip or icon label says "Exclude", click it to remove the subgroup.

8. Click on the multigroup name `test` once again to reopen its details window.  
   - **Note:** After the previous step, the **position of the multigroup `test` in the table may have changed**.  
     Be attentive and make sure you click on the correct **multigroup name** labeled exactly `test`.  
   - This will open a **popup details window directly below the `test` multigroup row** in the table.  
   - Inside this specific popup window, **scroll down** to the **Subgroups** section.  
   - Verify that the group named `example` is **no longer listed** among the subgroups.  
   - If the `example` group is still present, it means the removal **failed**.  
   - If it is not present, the removal was **successful**.
"""
