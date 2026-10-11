"""Troubleshooting playbook.

Everything here is a restructuring of the provider's own policy and technical
support manual (the documents every agent on the benchmark is given). It adds no
facts. What it changes is the shape: the manual explains each fault in its own
section, while the playbook is one ordered list per problem with an explicit
"keep going until verified" rule.
"""

PLAYBOOK = """
## How to run a technical support call

A phone that is misbehaving usually has SEVERAL faults at once. Fixing one rarely
finishes the job. Work the checklist for the customer's problem from top to bottom,
and keep going after each fix until the verification step passes.

### Talking to the customer about their phone
- The customer's phone offers exactly the actions listed under "What the user can do
  on their device". Ask for ONE action at a time, by its name, for example:
  "Please run check_network_status on your phone and tell me exactly what it shows."
- Never describe menus, screens or buttons. You cannot see their phone and would be
  guessing.
- Never assume an action was done. After every fix, ask the customer to run the
  matching check and read you the result.
- "toggle" actions flip the current state. Check the state first and only ask for a
  toggle when the state is wrong. Never toggle something off and on to "refresh" it.
- Only suggest fixes that are in the manual.
- If the customer is anxious or reluctant, reassure them in one sentence and repeat
  the single action you need. Do not offer to transfer them instead.

### Step 0, always
Identify the customer, then find the line that matches the phone number they gave
(look at each line on the account). Note that line's status, roaming setting, plan
and data usage. Ask whether they are abroad if they have not said.

### A. No service (status bar shows no signal, or airplane mode)
1. check_status_bar. Airplane mode on -> toggle_airplane_mode.
2. check_sim_status. "Missing" -> reseat_sim_card. "Locked" (PIN or PUK) -> transfer.
3. check_apn_settings. Incorrect -> reset_apn_settings, then reboot_device.
4. Line status. Suspended with an overdue bill -> take payment exactly as the policy
   describes, confirm the bill shows Paid, resume the line, then reboot_device.
   Suspended because the contract end date has passed -> transfer.
Verify: check_status_bar shows a signal.

### B. Mobile data not working or slow (do A first if there is no service)
1. If abroad: the line must be roaming enabled (enable it yourself if not) AND data
   roaming must be on in the phone (check_network_status; toggle_roaming if off).
   Check both, every time.
2. check_network_status. Mobile data off -> toggle_data.
3. Data usage against the plan limit (get_data_usage). Limit reached -> offer a refuel
   (2 GB maximum) or a plan change. State the price per GB and ask how many GB they
   want. Do not suggest an amount or say how much would be "enough": that is the
   customer's decision. Confirm the price for their amount, then apply exactly that.
4. check_data_restriction_status. Data Saver on -> toggle_data_saver_mode.
5. check_vpn_status. VPN connected -> disconnect_vpn.
6. check_network_mode_preference. 2G or 3G -> set_network_mode_preference to
   "4g_5g_preferred".
Verify: run_speed_test. Anything below "excellent" means a fault remains: continue
down the list, do not stop at the first improvement.

### C. Picture messages (MMS) not sending
MMS needs service and working mobile data, so run A and B first, including roaming
and the data limit.
1. Network type 2G -> set_network_mode_preference to "4g_5g_preferred".
2. check_wifi_calling_status. Wi-Fi Calling on -> toggle_wifi_calling.
3. check_apn_settings. MMSC URL missing -> reset_apn_settings, then reboot_device.
4. check_app_permissions for the "messaging" app. Grant "storage" and "sms" if either
   is missing (one grant_app_permission per permission).
Verify: can_send_mms. If it still fails, something above was skipped: go back and
check each item you have not confirmed.

### When to transfer to a human
Only in these cases:
- the SIM is locked, or
- the line is suspended because its contract has ended, or
- the request is outside technical support, billing, suspension and plans, or
- every item on the relevant checklist has been checked with the customer and the
  verification step still fails.
A frustrated customer, a fix that did not work, or weak signal are not reasons to
transfer. They are reasons to continue down the checklist.
""".strip()
