/* Generated into the P011 builder by patch_p011_xncp.py.
 * Identity only: no routing, retry, NVM, watchdog or network behavior changes.
 */
#include <stdint.h>
#include <string.h>
#include "sl_status.h"

#define P011_XNCP_MANUFACTURER_ID 0xFFFFu /* private/unassigned experimental namespace */
#define P011_XNCP_VERSION         0x010Bu /* schema 1, profile 11 */
#define P011_COMMAND_IDENTITY     0xA1u
#define P011_SCHEMA_VERSION       1u
#define P011_PROFILE_ID           11u
#define P011_CAP_IDENTITY         0x0001u

#if defined(__GNUC__)
#define P011_XNCP_ENTRY __attribute__((used, noinline, externally_visible))
#else
#define P011_XNCP_ENTRY
#endif

static const char p011_source_commit[] = "@@SOURCE_COMMIT@@";
static const uint8_t p011_resource_hash[16] = { @@RESOURCE_HASH_BYTES@@ };

static void p011_get_info(uint16_t *manufacturer_id, uint16_t *version_number)
{
    if (manufacturer_id != NULL) {
        *manufacturer_id = P011_XNCP_MANUFACTURER_ID;
    }
    if (version_number != NULL) {
        *version_number = P011_XNCP_VERSION;
    }
}

/* Older AF callback spelling retained as a strong override where supported. */
void emberAfPluginXncpGetXncpInformation(uint16_t *manufacturer_id, uint16_t *version_number)
{
    p011_get_info(manufacturer_id, version_number);
}

/* Simplicity-SDK callback spelling. Keeping both is harmless; only the framework
 * callback referenced by the selected XNCP component is invoked. */
P011_XNCP_ENTRY void sl_zigbee_af_xncp_get_xncp_information(uint16_t *manufacturer_id, uint16_t *version_number)
{
    p011_get_info(manufacturer_id, version_number);
}

P011_XNCP_ENTRY sl_status_t sl_zigbee_af_xncp_incoming_custom_frame_cb(
    uint8_t message_length,
    uint8_t *message_payload,
    uint8_t *reply_payload_length,
    uint8_t *reply_payload)
{
    uint8_t i;
    if (reply_payload_length == NULL || reply_payload == NULL) {
        return SL_STATUS_NULL_POINTER;
    }
    *reply_payload_length = 0;
    if (message_length != 1 || message_payload == NULL || message_payload[0] != P011_COMMAND_IDENTITY) {
        return SL_STATUS_NOT_SUPPORTED;
    }

    /* Binary v1 response:
     * command, status, schema, profile, capabilities LE16,
     * source commit ASCII[12], resource-profile SHA256 prefix[16].
     */
    reply_payload[0] = P011_COMMAND_IDENTITY;
    reply_payload[1] = 0;
    reply_payload[2] = P011_SCHEMA_VERSION;
    reply_payload[3] = P011_PROFILE_ID;
    reply_payload[4] = (uint8_t)(P011_CAP_IDENTITY & 0xFFu);
    reply_payload[5] = (uint8_t)((P011_CAP_IDENTITY >> 8) & 0xFFu);
    for (i = 0; i < 12; i++) {
        reply_payload[6 + i] = (uint8_t)p011_source_commit[i];
    }
    memcpy(&reply_payload[18], p011_resource_hash, sizeof(p011_resource_hash));
    *reply_payload_length = 34;
    return SL_STATUS_OK;
}
