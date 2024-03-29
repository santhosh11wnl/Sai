import copy
import os
import warnings
from argparse import ArgumentParser, Namespace
from pathlib import Path
import cv2

import mmcv
import numpy as np
import torch
from mmcv.image.misc import tensor2imgs
from mmcv.runner import load_checkpoint
from mmcv.utils.config import Config
from PIL import Image

try:
    import tesserocr
except ImportError:
    tesserocr = None

from mmocr.apis import init_detector
from mmocr.apis.inference import model_inference
from mmocr.core.visualize import det_recog_show_result
from mmocr.datasets.kie_dataset import KIEDataset
from mmocr.datasets.pipelines.crop import crop_img
from mmocr.models import build_detector
from mmocr.models.textdet.detectors import TextDetectorMixin
from mmocr.models.textrecog.recognizer import BaseRecognizer
from mmocr.utils import is_type_list
from mmocr.utils.box_util import stitch_boxes_into_lines
from mmocr.utils.fileio import list_from_file
from mmocr.utils.model import revert_sync_batchnorm


def xxyy2xyxy(det_recog_result):
    # print('det_recog_result:\n', det_recog_result[0])
    # print('len:', len(det_recog_result[0]['result']))
    for i in range(len(det_recog_result[0]['result'])):
        xyxy = [det_recog_result[0]['result'][i]['box'][0][0], det_recog_result[0]['result'][i]['box'][1][1],
                det_recog_result[0]['result'][i]['box'][0][0], det_recog_result[0]['result'][i]['box'][0][1],
                det_recog_result[0]['result'][i]['box'][1][0], det_recog_result[0]['result'][i]['box'][0][1],
                det_recog_result[0]['result'][i]['box'][1][0], det_recog_result[0]['result'][i]['box'][1][1]
                ]
        det_recog_result[0]['result'][i]['xyxy_box'] = xyxy
    return det_recog_result


class MMOCR:  ###  MMOCR(det=None, recog='CRNN_TPS')

    def __init__(self,
                 det='PANet_IC15',
                 det_config='',
                 det_ckpt='',
                 recog='SEG',
                 recog_config='',
                 recog_ckpt='',
                 kie='',
                 kie_config='',
                 kie_ckpt='',
                 config_dir=os.path.join(str(Path.cwd()), 'configs/'),
                 device=None,
                 **kwargs):

        textdet_models = {
            'DB_r18': {
                'config':
                    'dbnet/dbnet_r18_fpnc_1200e_icdar2015.py',
                'ckpt':
                    'dbnet/'
                    'dbnet_r18_fpnc_sbn_1200e_icdar2015_20210329-ba3ab597.pth'
            },
            'DB_r50': {
                'config':
                    'dbnet/dbnet_r50dcnv2_fpnc_1200e_icdar2015.py',
                'ckpt':
                    'dbnet/'
                    'dbnet_r50dcnv2_fpnc_sbn_1200e_icdar2015_20211025-9fe3b590.pth'
            },
            'DRRG': {
                'config':
                    'drrg/drrg_r50_fpn_unet_1200e_ctw1500.py',
                'ckpt':
                    'drrg/drrg_r50_fpn_unet_1200e_ctw1500_20211022-fb30b001.pth'
            },
            'FCE_IC15': {
                'config':
                    'fcenet/fcenet_r50_fpn_1500e_icdar2015.py',
                'ckpt':
                    'fcenet/fcenet_r50_fpn_1500e_icdar2015_20211022-daefb6ed.pth'
            },
            'FCE_CTW_DCNv2': {
                'config':
                    'fcenet/fcenet_r50dcnv2_fpn_1500e_ctw1500.py',
                'ckpt':
                    'fcenet/' +
                    'fcenet_r50dcnv2_fpn_1500e_ctw1500_20211022-e326d7ec.pth'
            },
            'MaskRCNN_CTW': {
                'config':
                    'maskrcnn/mask_rcnn_r50_fpn_160e_ctw1500.py',
                'ckpt':
                    'maskrcnn/'
                    'mask_rcnn_r50_fpn_160e_ctw1500_20210219-96497a76.pth'
            },
            'MaskRCNN_IC15': {
                'config':
                    'maskrcnn/mask_rcnn_r50_fpn_160e_icdar2015.py',
                'ckpt':
                    'maskrcnn/'
                    'mask_rcnn_r50_fpn_160e_icdar2015_20210219-8eb340a3.pth'
            },
            'MaskRCNN_IC17': {
                'config':
                    'maskrcnn/mask_rcnn_r50_fpn_160e_icdar2017.py',
                'ckpt':
                    'maskrcnn/'
                    'mask_rcnn_r50_fpn_160e_icdar2017_20210218-c6ec3ebb.pth'
            },
            'PANet_CTW': {
                'config':
                    'panet/panet_r18_fpem_ffm_600e_ctw1500.py',
                'ckpt':
                    'panet/'
                    'panet_r18_fpem_ffm_sbn_600e_ctw1500_20210219-3b3a9aa3.pth'
            },
            'PANet_IC15': {
                'config':
                    'panet/panet_r18_fpem_ffm_600e_icdar2015.py',
                'ckpt':
                    'panet/'
                    'panet_r18_fpem_ffm_sbn_600e_icdar2015_20210219-42dbe46a.pth'
            },
            'PS_CTW': {
                'config': 'psenet/psenet_r50_fpnf_600e_ctw1500.py',
                'ckpt':
                    'psenet/psenet_r50_fpnf_600e_ctw1500_20210401-216fed50.pth'
            },
            'PS_IC15': {
                'config':
                    'psenet/psenet_r50_fpnf_600e_icdar2015.py',
                'ckpt':
                    'psenet/psenet_r50_fpnf_600e_icdar2015_pretrain-eefd8fe6.pth'
            },
            'TextSnake': {
                'config':
                    'textsnake/textsnake_r50_fpn_unet_1200e_ctw1500.py',
                'ckpt':
                    'textsnake/textsnake_r50_fpn_unet_1200e_ctw1500-27f65b64.pth'
            },
            'Tesseract': {}
        }

        textrecog_models = {
            'CRNN': {
                'config': 'crnn/crnn_academic_dataset.py',
                'ckpt': 'crnn/crnn_academic-a723a1c5.pth'
            },
            'SAR': {
                'config': 'sar/sar_r31_parallel_decoder_academic.py',
                'ckpt': 'sar/sar_r31_parallel_decoder_academic-dba3a4a3.pth'
            },
            'SAR_CN': {
                'config':
                    'sar/sar_r31_parallel_decoder_chinese.py',
                'ckpt':
                    'sar/sar_r31_parallel_decoder_chineseocr_20210507-b4be8214.pth'
            },
            'NRTR_1/16-1/8': {
                'config': 'nrtr/nrtr_r31_1by16_1by8_academic.py',
                'ckpt':
                    'nrtr/nrtr_r31_1by16_1by8_academic_20211124-f60cebf4.pth'
            },
            'NRTR_1/8-1/4': {
                'config': 'nrtr/nrtr_r31_1by8_1by4_academic.py',
                'ckpt':
                    'nrtr/nrtr_r31_1by8_1by4_academic_20211123-e1fdb322.pth'
            },
            'RobustScanner': {
                'config': 'robust_scanner/robustscanner_r31_academic.py',
                'ckpt': 'robustscanner/robustscanner_r31_academic-5f05874f.pth'
            },
            'SATRN': {
                'config': 'satrn/satrn_academic.py',
                'ckpt': 'satrn/satrn_academic_20211009-cb8b1580.pth'
            },
            'SATRN_sm': {
                'config': 'satrn/satrn_small.py',
                'ckpt': 'satrn/satrn_small_20211009-2cf13355.pth'
            },
            'ABINet': {
                'config': 'abinet/abinet_academic.py',
                'ckpt': 'abinet/abinet_academic-f718abf6.pth'
            },
            'SEG': {
                'config': 'seg/seg_r31_1by16_fpnocr_academic.py',
                'ckpt': 'seg/seg_r31_1by16_fpnocr_academic-72235b11.pth'
            },
            'CRNN_TPS': {
                'config': 'tps/crnn_tps_academic_dataset.py',
                'ckpt': 'tps/crnn_tps_academic_dataset_20210510-d221a905.pth'
            },
            'Tesseract': {}
        }

        kie_models = {
            'SDMGR': {
                'config': 'sdmgr/sdmgr_unet16_60e_wildreceipt.py',
                'ckpt':
                    'sdmgr/sdmgr_unet16_60e_wildreceipt_20210520-7489e6de.pth'
            }
        }

        self.td = det
        self.tr = recog
        self.kie = kie
        self.device = device
        if self.device is None:
            self.device = torch.device(
                'cuda' if torch.cuda.is_available() else 'cpu')
        print(self.device)
        # Check if the det/recog model choice is valid
        if self.td and self.td not in textdet_models:
            raise ValueError(self.td,
                             'is not a supported text detection algorthm')
        elif self.tr and self.tr not in textrecog_models:
            raise ValueError(self.tr,
                             'is not a supported text recognition algorithm')
        elif self.kie:
            if self.kie not in kie_models:
                raise ValueError(
                    self.kie, 'is not a supported key information extraction'
                              ' algorithm')
            elif not (self.td and self.tr):
                raise NotImplementedError(
                    self.kie, 'has to run together'
                              ' with text detection and recognition algorithms.')

        self.detect_model = None
        if self.td and self.td == 'Tesseract':
            if tesserocr is None:
                raise ImportError('Please install tesserocr first. '
                                  'Check out the installation guide at '
                                  'https://github.com/sirfz/tesserocr')
            self.detect_model = 'Tesseract_det'
        elif self.td:
            # Build detection model
            if not det_config:
                det_config = os.path.join(config_dir, 'textdet/',
                                          textdet_models[self.td]['config'])
            if not det_ckpt:
                det_ckpt = 'https://download.openmmlab.com/mmocr/textdet/' + \
                           textdet_models[self.td]['ckpt']

            self.detect_model = init_detector(
                det_config, det_ckpt, device=self.device)
            self.detect_model = revert_sync_batchnorm(self.detect_model)

        self.recog_model = None
        if self.tr and self.tr == 'Tesseract':
            if tesserocr is None:
                raise ImportError('Please install tesserocr first. '
                                  'Check out the installation guide at '
                                  'https://github.com/sirfz/tesserocr')
            self.recog_model = 'Tesseract_recog'
        elif self.tr:
            # Build recognition model
            if not recog_config:
                recog_config = os.path.join(
                    config_dir, 'textrecog/',
                    textrecog_models[self.tr]['config'])
            if not recog_ckpt:
                recog_ckpt = 'https://download.openmmlab.com/mmocr/' + \
                             'textrecog/' + textrecog_models[self.tr]['ckpt']

            self.recog_model = init_detector(
                recog_config, recog_ckpt, device=self.device)
            self.recog_model = revert_sync_batchnorm(self.recog_model)

        self.kie_model = None
        if self.kie:
            # Build key information extraction model
            if not kie_config:
                kie_config = os.path.join(config_dir, 'kie/',
                                          kie_models[self.kie]['config'])
            if not kie_ckpt:
                kie_ckpt = 'https://download.openmmlab.com/mmocr/' + \
                           'kie/' + kie_models[self.kie]['ckpt']

            kie_cfg = Config.fromfile(kie_config)
            self.kie_model = build_detector(
                kie_cfg.model, test_cfg=kie_cfg.get('test_cfg'))
            self.kie_model = revert_sync_batchnorm(self.kie_model)
            self.kie_model.cfg = kie_cfg
            load_checkpoint(self.kie_model, kie_ckpt, map_location=self.device)

        # Attribute check
        for model in list(filter(None, [self.recog_model, self.detect_model])):
            if hasattr(model, 'module'):
                model = model.module

    def readtext(self,
                 img,
                 output=None,
                 details=False,
                 export=None,
                 export_format='json',
                 batch_mode=False,
                 recog_batch_size=0,
                 det_batch_size=0,
                 single_batch_size=0,
                 imshow=False,
                 print_result=False,
                 merge=False,
                 merge_xdist=20,
                 **kwargs):
        args = locals().copy()
        [args.pop(x, None) for x in ['kwargs', 'self']]
        args = Namespace(**args)

        # Input and output arguments processing
        self._args_processing(args)
        self.args = args

        pp_result = None
        box_result = None

        # Send args and models to the MMOCR model inference API
        # and call post-processing functions for the output
        if self.detect_model and self.recog_model:
            det_recog_result = self.det_recog_kie_inference(self.detect_model, self.recog_model,
                                                            kie_model=self.kie_model)
            # print('det_recog_result:\n', det_recog_result)
            det_recog_result = xxyy2xyxy(det_recog_result)
            # print('det_recog_result:\n', det_recog_result)
            pp_result, box_result = self.det_recog_pp(det_recog_result)
        else:
            # print('filename:', self.args.filenames)
            for model in list(filter(None, [self.recog_model, self.detect_model])):
                pp_result = []
                ppresult = None
                # print('args:', args)
                # print('kwargs:', kwargs)
                for index in range(len(args.arrays)):
                    # print('len:', len(args.arrays), '   index:', index)
                    # print(index, '---',args.arrays[index])
                    if len(args.arrays[index]) < 1:
                        continue
                    # cv2.imwrite(
                    #     r'result1/' + self.args.filenames[index] + '.jpg',
                    #     args.arrays[index])
                    result = model_inference(model, args.arrays[index])
                    ppresult = self.single_pp(result, model)
                    # print('pp_result:', ppresult['text'])
                    pp_result.append(ppresult['text'])
                box_result = []   ###

        return pp_result, box_result

    # Post processing function for end2end ocr
    def det_recog_pp(self, result):
        # print('args.output:', self.args.output)
        final_results = []
        box_results = []
        args = self.args
        for arr, output, export, det_recog_result in zip(
                args.arrays, args.output, args.export, result):
            if output or args.imshow:
                if self.kie_model:
                    res_img = det_recog_show_result(arr, det_recog_result)
                else:
                    res_img = det_recog_show_result(
                        arr, det_recog_result, out_file=output)
                if args.imshow and not self.kie_model:
                    mmcv.imshow(res_img, 'inference results')
            if not args.details:
                simple_res = {}
                simple_res['filename'] = det_recog_result['filename']
                simple_res['text'] = [
                    x['text'] for x in det_recog_result['result']
                ]
                simple_res['text_num'] = len(simple_res['text'])
                # simple_res['text_score'] = [
                #     y['text_score'] for y in det_recog_result['result']
                # ]
                final_result = simple_res

                box_res = {}
                box_res['filename'] = det_recog_result['filename']
                box_res['box'] = [
                    x['box'] for x in det_recog_result['result']
                ]
                box_res['text_num'] = len(box_res['box'])
                box_result = box_res
            else:
                final_result = det_recog_result
            if export:
                mmcv.dump(final_result, export, indent=4)
            if args.print_result:
                print(final_result, end='\n\n')
                print(box_result, end='\n\n')
            final_results.append(final_result)
            box_results.append(box_result)
        return final_results, box_results

    # Post processing function for separate det/recog inference
    def single_pp(self, result, model):
        for arr, output, export, res in zip(self.args.arrays, self.args.output,
                                            self.args.export, result):
            if export:
                mmcv.dump(res, export, indent=4)
            if output or self.args.imshow:
                if model == 'Tesseract_det':
                    res_img = TextDetectorMixin(show_score=False).show_result(
                        arr, res, out_file=output)
                elif model == 'Tesseract_recog':
                    res_img = BaseRecognizer.show_result(
                        arr, res, out_file=output)
                else:
                    res_img = model.show_result(arr, res, out_file=output)
                if self.args.imshow:
                    mmcv.imshow(res_img, 'inference results')
            if self.args.print_result:
                print(res, end='\n\n')
        return result

    def generate_kie_labels(self, result, boxes, class_list):
        idx_to_cls = {}
        if class_list is not None:
            for line in list_from_file(class_list):
                class_idx, class_label = line.strip().split()
                idx_to_cls[class_idx] = class_label

        max_value, max_idx = torch.max(result['nodes'].detach().cpu(), -1)
        node_pred_label = max_idx.numpy().tolist()
        node_pred_score = max_value.numpy().tolist()
        labels = []
        for i in range(len(boxes)):
            pred_label = str(node_pred_label[i])
            if pred_label in idx_to_cls:
                pred_label = idx_to_cls[pred_label]
            pred_score = node_pred_score[i]
            labels.append((pred_label, pred_score))
        return labels

    def visualize_kie_output(self,
                             model,
                             data,
                             result,
                             out_file=None,
                             show=False):
        """Visualizes KIE output."""
        img_tensor = data['img'].data
        img_meta = data['img_metas'].data
        gt_bboxes = data['gt_bboxes'].data.numpy().tolist()
        if img_tensor.dtype == torch.uint8:
            # The img tensor is the raw input not being normalized
            # (For SDMGR non-visual)
            img = img_tensor.cpu().numpy().transpose(1, 2, 0)
        else:
            img = tensor2imgs(
                img_tensor.unsqueeze(0), **img_meta.get('img_norm_cfg', {}))[0]
        h, w, _ = img_meta.get('img_shape', img.shape)
        img_show = img[:h, :w, :]
        model.show_result(
            img_show, result, gt_bboxes, show=show, out_file=out_file)

    # End2end ocr inference pipeline
    def det_recog_kie_inference(self, det_model, recog_model, kie_model=None):
        end2end_res = []
        # Find bounding boxes in the images (text detection)
        det_result = self.single_inference(det_model, self.args.arrays,
                                           self.args.batch_mode,
                                           self.args.det_batch_size)
        bboxes_list = [res['boundary_result'] for res in det_result]

        if kie_model:
            kie_dataset = KIEDataset(
                dict_file=kie_model.cfg.data.test.dict_file)

        # For each bounding box, the image is cropped and
        # sent to the recognition model either one by one
        # or all together depending on the batch_mode
        # 对于每个边界框，图像被裁剪并一个接一个地发送到识别模型
        for filename, arr, bboxes, out_file in zip(self.args.filenames,
                                                   self.args.arrays,
                                                   bboxes_list,
                                                   self.args.output):
            img_e2e_res = {}
            img_e2e_res['filename'] = filename
            img_e2e_res['result'] = []
            # img_e2e_res['box'] = []
            box_imgs = []
            for bbox in bboxes:
                box_res = {}
                # box_res['box'] = [round(x) for x in bbox[:-1]]  # round() 向上取整
                box_res['box_score'] = float(bbox[-1])
                box = bbox[:8]
                if len(bbox) > 9:
                    min_x = min(bbox[0:-1:2])
                    min_y = min(bbox[1:-1:2])
                    max_x = max(bbox[0:-1:2])
                    max_y = max(bbox[1:-1:2])
                    box = [
                        min_x, min_y, max_x, min_y, max_x, max_y, min_x, max_y
                    ]
                # img_e2e_res['box'] = box
                box_img, left, top, right, bottom = crop_img(arr, box)
                box_res['box'] = [[left, top], [right, bottom]]
                # cv2.imwrite('result/' + filename + str(bboxes.index(bbox)) + '.jpg', box_img)
                # print(filename + str(bboxes.index(bbox)))
                # print(type(box_img))
                if self.args.batch_mode:
                    box_imgs.append(box_img)
                else:
                    if recog_model == 'Tesseract_recog':
                        recog_result = self.single_inference(
                            recog_model, box_img, batch_mode=True)
                    else:
                        recog_result = model_inference(recog_model, box_img)  # 将crop后的小图用recog_model做inference
                    text = recog_result['text']
                    text_score = recog_result['score']
                    if isinstance(text_score, list):
                        text_score = sum(text_score) / max(1, len(text))
                    box_res['text'] = text
                    box_res['text_score'] = text_score
                img_e2e_res['result'].append(box_res)

            if self.args.batch_mode:
                recog_results = self.single_inference(
                    recog_model, box_imgs, True, self.args.recog_batch_size)
                for i, recog_result in enumerate(recog_results):
                    text = recog_result['text']
                    text_score = recog_result['score']
                    if isinstance(text_score, (list, tuple)):
                        text_score = sum(text_score) / max(1, len(text))
                    img_e2e_res['result'][i]['text'] = text
                    img_e2e_res['result'][i]['text_score'] = text_score

            if self.args.merge:
                img_e2e_res['result'] = stitch_boxes_into_lines(
                    img_e2e_res['result'], self.args.merge_xdist, 0.5)

            if kie_model:
                annotations = copy.deepcopy(img_e2e_res['result'])
                # Customized for kie_dataset, which
                # assumes that boxes are represented by only 4 points
                for i, ann in enumerate(annotations):
                    min_x = min(ann['box'][::2])
                    min_y = min(ann['box'][1::2])
                    max_x = max(ann['box'][::2])
                    max_y = max(ann['box'][1::2])
                    annotations[i]['box'] = [
                        min_x, min_y, max_x, min_y, max_x, max_y, min_x, max_y
                    ]
                ann_info = kie_dataset._parse_anno_info(annotations)
                ann_info['ori_bboxes'] = ann_info.get('ori_bboxes',
                                                      ann_info['bboxes'])
                ann_info['gt_bboxes'] = ann_info.get('gt_bboxes',
                                                     ann_info['bboxes'])
                kie_result, data = model_inference(
                    kie_model,
                    arr,
                    ann=ann_info,
                    return_data=True,
                    batch_mode=self.args.batch_mode)
                # visualize KIE results
                self.visualize_kie_output(
                    kie_model,
                    data,
                    kie_result,
                    out_file=out_file,
                    show=self.args.imshow)
                gt_bboxes = data['gt_bboxes'].data.numpy().tolist()
                labels = self.generate_kie_labels(kie_result, gt_bboxes,
                                                  kie_model.class_list)
                for i in range(len(gt_bboxes)):
                    img_e2e_res['result'][i]['label'] = labels[i][0]
                    img_e2e_res['result'][i]['label_score'] = labels[i][1]

            end2end_res.append(img_e2e_res)
        return end2end_res

    # Separate det/recog inference pipeline
    def single_inference(self, model, arrays, batch_mode, batch_size=0):

        def inference(m, a, **kwargs):
            if model == 'Tesseract_det':
                print('Tesseract_det')
            elif model == 'Tesseract_recog':
                print('Tesseract_recog')
            else:
                return model_inference(m, a, **kwargs)

        result = []
        if batch_mode:
            if batch_size == 0:
                result = inference(model, arrays, batch_mode=True)
            else:
                n = batch_size
                arr_chunks = [
                    arrays[i:i + n] for i in range(0, len(arrays), n)
                ]
                for chunk in arr_chunks:
                    result.extend(inference(model, chunk, batch_mode=True))
        else:
            for arr in arrays:
                result.append(inference(model, arr, batch_mode=False))
        return result

    # Arguments pre-processing function
    def _args_processing(self, args):
        # Check if the input is a list/tuple that
        # contains only np arrays or strings
        if isinstance(args.img, (list, tuple)):
            img_list = args.img
            if not all([isinstance(x, (np.ndarray, str)) for x in args.img]):
                raise AssertionError('Images must be strings or numpy arrays')

        # Create a list of the images
        if isinstance(args.img, str):
            img_path = Path(args.img)
            if img_path.is_dir():
                img_list = [str(x) for x in img_path.glob('*')]
            else:
                img_list = [str(img_path)]
        elif isinstance(args.img, np.ndarray):
            img_list = [args.img]

        # Read all image(s) in advance to reduce wasted time
        # re-reading the images for visualization output
        args.arrays = [mmcv.imread(x) for x in img_list]

        # Create a list of filenames (used for output images and result files)
        if isinstance(img_list[0], str):
            args.filenames = [str(Path(x).stem) for x in img_list]
        else:
            args.filenames = [str(x) for x in range(len(img_list))]

        # If given an output argument, create a list of output image filenames
        num_res = len(img_list)
        if args.output:
            output_path = Path(args.output)
            if output_path.is_dir():
                args.output = [
                    str(output_path / f'out_{x}.png') for x in args.filenames
                ]
            else:
                args.output = [str(args.output)]
                if args.batch_mode:
                    raise AssertionError('Output of multiple images inference'
                                         ' must be a directory')
        else:
            args.output = [None] * num_res

        # If given an export argument, create a list of
        # result filenames for each image
        if args.export:
            export_path = Path(args.export)
            args.export = [
                str(export_path / f'out_{x}.{args.export_format}')
                for x in args.filenames
            ]
        else:
            args.export = [None] * num_res

        return args


# img_path = 'demo/demo_text_ocr.jpg'
img_path = 'demo/test.jpg'
output_path = 'result/'
# ocr = MMOCR(det=None, recog='CRNN_TPS')
# ocr = MMOCR()
# ocr.readtext(img=img_path, output=output_path, print_result=True)  # , imshow=True


def mmocr_f(det='PANet_IC15', recog='SEG', img=None, output=None, print_result=False):
    ocr = MMOCR(det=det, recog=recog)
    text, box = ocr.readtext(img=img, output=output, print_result=print_result)
    return text, box

def cropimg(src_img, box):
    top = box[0]
    bottom = box[1]
    left = box[2]
    right = box[3]
    dst_img = src_img[top:bottom, left:right]
    # print('crop:', top, bottom, left, right)
    return dst_img


def mmocr_without_det(det=None, recog='SEG', img=None, element_bbox=None, output=None):
    img_crops = []
    boxs = []
    img_cv = cv2.imread(img)
    for index in element_bbox.index:
        min_x = round(element_bbox.loc[index][0])
        min_y = round(element_bbox.loc[index][1])
        max_x = min_x + round(element_bbox.loc[index][2])
        max_y = min_y + round(element_bbox.loc[index][3])
        box = [
            min_y, max_y, min_x, max_x
        ]
        boxx = [[min_x, min_y], [max_x, max_y]]
        # print('box:', box)
        img_crop = cropimg(img_cv, box)
        img_crops.append(img_crop)
        boxs.append(boxx)
    ocr = MMOCR(det=det, recog=recog)
    mmocr_results = ocr.readtext(img_crops)
    box_text_list = []
    # box_text_dit = {}
    # det_recog_result = [{'result': box_text_list}]

    for i in range(len(mmocr_results[0])):
        box_text_dit = {}
        box_text_dit['text'] = mmocr_results[0][i]
        box_text_dit['box'] = boxs[i]
        box_text_list.append(box_text_dit)

    # print('list:', box_text_list)

    det_recog_result = [{'result': box_text_list}]
    det_recog_result = xxyy2xyxy(det_recog_result)
    det_recog_result = det_recog_result[0]
    # print('det_recog_result:\n', det_recog_result)
    res_img = det_recog_show_result(
        img, det_recog_result, out_file=output)

    return mmocr_results, boxs


if __name__ == "__main__":
    text, box = mmocr_f(img=img_path, output=output_path, print_result=True)
    print('text:', text)
    print('box:', box)




