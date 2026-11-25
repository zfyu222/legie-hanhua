/* LEGIE Steam PE32. The caller keeps byte-based sprite names. A four-byte
   escape (~000..~fff) creates one sprite and skips its payload consistently
   during construction, deletion, repositioning, and opacity updates. */
.intel_syntax noprefix
.text
.globl preload, draw_glyph, delete_glyph, move_glyph, fade_glyph
.globl glyph_names

preload:
    push dword ptr [esp+4]
    call original_preload
    push ebx
    push esi
    push edi
    call .Lpreload_base
.Lpreload_base:
    pop esi
    add esi, glyph_names - .Lpreload_base
    mov edi, OFFSET FLAT:glyph_count
    test edi, edi
    jz .Lpreload_done
.Lpreload_loop:
    lea eax, [esi+8]
    call load_glyph_material
    add esi, 16
    dec edi
    jnz .Lpreload_loop
.Lpreload_done:
    pop edi
    pop esi
    pop ebx
    ret 4

draw_glyph:
    cmp al, '~'
    je .Lchinese
.Loriginal:
    cmp al, ' '
    je draw_space
    lea edx, [ebp-0xc]
    jmp draw_original
.Lchinese:
    cmp esi, 4
    jb .Loriginal
    mov eax, [ebp+0x10]
    lea eax, [eax+ebx]
    xor ecx, ecx
    mov edx, 3
.Ldecode:
    movzx eax, byte ptr [eax]
    cmp al, '9'
    jbe .Ldigit
    sub al, 'a'-10-'0'
.Ldigit:
    sub al, '0'
    cmp al, 15
    ja .Linvalid
    shl ecx, 4
    or ecx, eax
    dec edx
    jz .Ldecode_done
    push ecx
    mov eax, [ebp+0x10]
    lea eax, [eax+ebx+3]
    sub eax, edx
    pop ecx
    jmp .Ldecode
.Ldecode_done:
    cmp ecx, OFFSET FLAT:glyph_count
    jae .Linvalid
    shl ecx, 4
    call .Ldraw_base
.Ldraw_base:
    pop edx
    lea edx, [edx+ecx+glyph_names-.Ldraw_base+8]
    lea eax, [ebp-0xc]
    call assign_string
    push ebp
    mov eax, edi
    mov ecx, ebx
    mov edx, [ebp-0x10]
    call make_sprite
    pop ecx
    add edi, 16
    add dword ptr [ebp-0x18], 16
    add ebx, 3
    sub esi, 3
    jmp draw_next
.Linvalid:
    mov al, '?'
    jmp .Loriginal

/* Keep the original sprite name for the prefix byte and advance past the
   three payload bytes before the engine moves to the next character. */
.macro sprite_loop label, index, remaining, local, original, lookup, next
\label:
    cmp byte ptr [eax+\index-1], ' '
    je \next
    cmp byte ptr [eax+\index-1], '~'
    jne \original
    cmp \remaining, 4
    jb \original
    sub \remaining, 3
    lea ecx, [ebp-\local]
    mov edx, \index
    mov eax, ebx
    call sprite_name
    add \index, 3
    jmp \lookup
.endm

sprite_loop delete_glyph, edi, esi, 4, delete_original, delete_lookup, delete_next
sprite_loop move_glyph, esi, edi, 0x10, move_original, move_lookup, move_next
sprite_loop fade_glyph, edi, esi, 4, fade_original, fade_lookup, fade_next

.balign 16
glyph_names:
