# Exchange Online Authentication Fix

**Date:** October 22, 2025 14:32 UTC  
**Lambda:** brie-infrastructure-connector  
**Issue:** Shared mailbox operations failing with error `0xffffffff80070520`

## Root Cause

The shared mailbox operations were using **username/password authentication** which was failing:

```powershell
$SecurePassword = ConvertTo-SecureString 'Zasa345270Zasa345270' -AsPlainText -Force
$Credential = New-Object System.Management.Automation.PSCredential ('svc-exchange-automation@ever.ag', $SecurePassword)
Connect-ExchangeOnline -Credential $Credential -ShowBanner:$false
```

**Error:** `0xffffffff80070520` - MSAL authentication failure

**Why it failed:**
- Username/password authentication is deprecated by Microsoft
- Service account credentials may be expired/invalid
- Modern authentication requires certificate-based auth

## Solution

Replaced username/password authentication with **certificate-based authentication** (same method used for distribution groups):

```powershell
$AppId = 'c33fc45c-9313-4f45-ac31-baf568616137'
$Organization = 'ever.ag'
$CertificateThumbprint = '5A9D9A9076B309B70828EBB3C9AE57496DB68421'
Connect-ExchangeOnline -AppId $AppId -CertificateThumbprint $CertificateThumbprint -Organization $Organization -ShowBanner:$false
```

## Changes Made

Updated three functions in `brie-infrastructure-connector.py`:

1. **Line 774-784:** `add_user_to_shared_mailbox` - Permission check script
2. **Line 830-838:** `add_user_to_shared_mailbox` - Add permission script  
3. **Line 706-716:** `search_mailbox` - Mailbox search script

All now use certificate-based authentication with:
- **App ID:** c33fc45c-9313-4f45-ac31-baf568616137 (Brie-IT-Automation-Group-Manager)
- **Certificate:** 5A9D9A9076B309B70828EBB3C9AE57496DB68421
- **Organization:** ever.ag

## Deployment

```bash
cd ~/Brie-IT-Agent/lambda
zip brie-infrastructure-connector.zip brie-infrastructure-connector.py
aws lambda update-function-code \
  --function-name brie-infrastructure-connector \
  --zip-file fileb://brie-infrastructure-connector.zip \
  --profile AWSCorp \
  --region us-east-1
```

**Deployed:** 2025-10-22T14:32:06.000+0000

## Testing Required

1. Request shared mailbox access via Slack bot
2. Verify approval appears in IT channel
3. Approve the request
4. Confirm user is successfully added to shared mailbox
5. Check CloudWatch logs for successful Exchange Online connection

## Expected Outcome

- ✅ No more `0xffffffff80070520` errors
- ✅ Shared mailbox operations complete successfully
- ✅ Users receive success notifications
- ✅ Consistent authentication method across all Exchange Online operations

## Notes

- Certificate must be installed on Bespin instance (i-0dca7766c8de43f08)
- Certificate thumbprint: 5A9D9A9076B309B70828EBB3C9AE57496DB68421
- If certificate expires, all Exchange Online operations will fail
- Monitor certificate expiration date
